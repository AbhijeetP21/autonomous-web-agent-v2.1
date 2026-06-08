"""Reliability controller: retry/backoff, loop detection, and a step budget.

Wraps execution so the agent loop degrades gracefully instead of crashing or
spiralling:
  - transient Playwright errors are retried with exponential backoff;
  - invalid/structural errors are returned as failed results so the planner re-plans;
  - repeating the same action on an unchanged page trips loop detection.
"""

from __future__ import annotations

import asyncio

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from web_agent.actions.schema import Action
from web_agent.executor.playwright_executor import ActionResult


def _signature(action: Action) -> str:
    a = action
    return "|".join(
        str(x) for x in (a.type.value, a.element_id, a.url, a.text, a.value, a.direction)
    )


class ReliabilityController:
    def __init__(self, max_steps: int = 25, retry_max: int = 3, loop_window: int = 3,
                 base_backoff: float = 0.3):
        self.max_steps = max_steps
        self.retry_max = retry_max
        self.loop_window = max(2, loop_window)
        self.base_backoff = base_backoff
        self.recovered = 0
        self._tail: list[str] = []   # recent (dom_hash + action signature) keys
        self._stuck = False

    # --- loop detection -----------------------------------------------------
    def before_action(self, dom_hash: str, action: Action) -> str | None:
        """Record intent; return a nudge string if we're starting to loop."""
        key = f"{dom_hash}#{_signature(action)}"
        self._tail.append(key)
        run_len = 1
        for prev in reversed(self._tail[:-1]):
            if prev == key:
                run_len += 1
            else:
                break
        if run_len >= self.loop_window:
            self._stuck = True
            return (
                "You have repeated the same action on an unchanged page several times "
                "without progress. Try a DIFFERENT element or approach, or finish."
            )
        if run_len == self.loop_window - 1:
            return (
                "This action appears to be repeating with no effect. "
                "Consider a different element or approach."
            )
        return None

    def is_stuck(self) -> bool:
        return self._stuck

    def note_error(self) -> None:
        """A planning/execution exception was caught and recovered into a re-plan."""
        self.recovered += 1

    # --- retry with backoff -------------------------------------------------
    async def execute_with_retry(self, executor, action: Action, obs) -> ActionResult:
        attempt = 0
        while True:
            try:
                return await executor.execute(action, obs)
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                attempt += 1
                if attempt > self.retry_max:
                    return ActionResult(
                        ok=False, error="playwright_error",
                        outcome=f"action failed after {self.retry_max} retries: {e}",
                    )
                self.recovered += 1
                await asyncio.sleep(self.base_backoff * (2 ** (attempt - 1)))
            except KeyError as e:
                # Stale/invalid element id — not transient; let the planner re-plan.
                return ActionResult(ok=False, error="bad_element", outcome=str(e))
