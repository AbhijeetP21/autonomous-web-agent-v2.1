"""Playwright executor.

Resolves a validated :class:`Action` against the live page. Element-targeting
actions are resolved by the ``data-agent-id`` assigned during perception, so the
model only ever deals in stable integer ids. Enforces the navigation domain
allowlist and (optionally) a confirmation gate for sensitive actions.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel

from web_agent.actions.schema import SENSITIVE, Action, ActionType
from web_agent.perception.accessibility import Observation


class ActionResult(BaseModel):
    ok: bool
    outcome: str
    error: str | None = None
    # Set when finish/ask_user is reached, so the agent loop can terminate.
    terminal: bool = False


class Executor:
    def __init__(
        self,
        page,
        allowed_domains: list[str],
        confirm_sensitive: bool = False,
        confirm_cb=None,
    ):
        self.page = page
        self.allowed_domains = [d.lower() for d in allowed_domains]
        self.confirm_sensitive = confirm_sensitive
        self.confirm_cb = confirm_cb

    def _domain_allowed(self, url: str) -> bool:
        if not self.allowed_domains:
            return True
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.allowed_domains)

    def _locator(self, element_id: int, observation: Observation):
        if element_id not in observation.element_ids():
            raise KeyError(
                f"element_id {element_id} is not in the current observation "
                f"(valid ids: {sorted(observation.element_ids())})"
            )
        return self.page.locator(f'[data-agent-id="{element_id}"]')

    async def execute(self, action: Action, observation: Observation) -> ActionResult:
        # Guardrail: confirmation gate for sensitive actions.
        if self.confirm_sensitive and action.type in SENSITIVE:
            approved = bool(self.confirm_cb and self.confirm_cb(action))
            if not approved:
                return ActionResult(
                    ok=False, error="blocked",
                    outcome=f"blocked (needs confirmation): {action.describe()}",
                )

        t = action.type
        if t is ActionType.FINISH:
            return ActionResult(
                ok=True, terminal=True,
                outcome=f"finished (success={action.success}): {action.summary}",
            )
        if t is ActionType.ASK_USER:
            return ActionResult(ok=True, terminal=True, outcome=f"asked user: {action.question}")

        if t is ActionType.NAVIGATE:
            if not self._domain_allowed(action.url):
                return ActionResult(
                    ok=False, error="domain_blocked",
                    outcome=f"navigation to {action.url} blocked by domain allowlist",
                )
            await self.page.goto(action.url, wait_until="domcontentloaded")
            return ActionResult(ok=True, outcome=f"navigated to {self.page.url}")

        if t is ActionType.WAIT:
            await self.page.wait_for_timeout(action.ms)
            return ActionResult(ok=True, outcome=f"waited {action.ms}ms")

        if t is ActionType.SCROLL:
            dy = 600 if action.direction == "down" else -600
            await self.page.mouse.wheel(0, dy)
            return ActionResult(ok=True, outcome=f"scrolled {action.direction}")

        # Element-targeting actions.
        target = observation.element(action.element_id)
        if target is not None and target.disabled:
            # A disabled element will never satisfy Playwright's actionability check, so
            # retrying just burns the timeout. Fail fast and let the planner re-plan.
            return ActionResult(
                ok=False, error="disabled",
                outcome=f"element [{action.element_id}] ({target.name!r}) is disabled",
            )
        loc = self._locator(action.element_id, observation)
        if t is ActionType.CLICK:
            await loc.click(timeout=5000)
            return ActionResult(ok=True, outcome=f"clicked element [{action.element_id}]")
        if t is ActionType.TYPE:
            await loc.fill(action.text, timeout=5000)
            if action.submit:
                await loc.press("Enter")
            return ActionResult(
                ok=True,
                outcome=f"typed into element [{action.element_id}]"
                + (" and submitted" if action.submit else ""),
            )
        if t is ActionType.SELECT:
            await loc.select_option(action.value, timeout=5000)
            return ActionResult(
                ok=True, outcome=f"selected {action.value!r} in [{action.element_id}]"
            )

        return ActionResult(ok=False, error="unsupported", outcome=f"unsupported action {t}")
