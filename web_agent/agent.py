"""The autonomous agent loop: perceive -> plan (LLM) -> act (Playwright) -> record.

This is the MVP orchestration. The reliability layer (retry/backoff, loop detection,
re-planning) is layered in on top of this loop in :mod:`web_agent.reliability`.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from pydantic import BaseModel

from web_agent.actions.schema import ActionType
from web_agent.browser import browser_page
from web_agent.config import Settings, get_settings
from web_agent.executor.playwright_executor import Executor
from web_agent.llm.base import LLMClient
from web_agent.observability.trace import StepTrace
from web_agent.perception.accessibility import Observation, perceive
from web_agent.planner.planner import Planner
from web_agent.reliability.controller import ReliabilityController
from web_agent.storage.repository import Repository


class RunResult(BaseModel):
    run_id: int
    status: str
    steps: int
    recovered: int = 0
    summary: str = ""


def _dom_hash(obs: Observation) -> str:
    return hashlib.md5(obs.to_prompt().encode("utf-8")).hexdigest()[:16]


class Agent:
    def __init__(
        self,
        client: LLMClient,
        repo: Repository,
        settings: Settings | None = None,
        confirm_cb=None,
    ):
        self.client = client
        self.repo = repo
        self.settings = settings or get_settings()
        self.planner = Planner(client)
        self.confirm_cb = confirm_cb

    async def run(self, goal: str, target_url: str, page=None) -> RunResult:
        if page is not None:
            run_id = self.repo.create_run(goal, target_url, self.settings.llm_provider,
                                          self.settings.llm_model)
            await page.goto(target_url, wait_until="domcontentloaded")
            return await self._loop(run_id, goal, page)
        async with browser_page(headless=self.settings.agent_headless) as p:
            run_id = self.repo.create_run(goal, target_url, self.settings.llm_provider,
                                          self.settings.llm_model)
            await p.goto(target_url, wait_until="domcontentloaded")
            return await self._loop(run_id, goal, p)

    async def resume(self, run_id: int, page=None) -> RunResult:
        """Continue an interrupted run from its last recorded step + page."""
        run = self.repo.get_run(run_id)
        if run is None:
            raise ValueError(f"no run {run_id}")
        if run.status not in ("running", "interrupted"):
            raise ValueError(f"run {run_id} is {run.status}; only running/interrupted can resume")
        steps = self.repo.get_steps(run_id)
        history = [f"step {s.step_index}: {s.action_type} -> {s.outcome or s.error}" for s in steps]
        resume_url = steps[-1].page_url if steps else run.target_url
        self.repo.set_status(run_id, "running")

        if page is not None:
            await page.goto(resume_url, wait_until="domcontentloaded")
            return await self._loop(run_id, run.goal, page, history=history,
                                    start_index=len(steps), base_recovered=run.recovered)
        async with browser_page(headless=self.settings.agent_headless) as p:
            await p.goto(resume_url, wait_until="domcontentloaded")
            return await self._loop(run_id, run.goal, p, history=history,
                                    start_index=len(steps), base_recovered=run.recovered)

    async def _loop(self, run_id: int, goal: str, page, history: list[str] | None = None,
                    start_index: int = 0, base_recovered: int = 0) -> RunResult:
        s = self.settings
        executor = Executor(page, s.allowed_domains, s.agent_confirm_sensitive, self.confirm_cb)
        rc = ReliabilityController(max_steps=s.agent_max_steps,
                                   retry_max=s.agent_retry_max,
                                   loop_window=s.agent_loop_window)
        history = history or []
        shot_dir = Path(s.screenshot_dir) / f"run_{run_id}"
        shot_dir.mkdir(parents=True, exist_ok=True)

        status, summary = "failed", ""
        step_index = start_index
        try:
            while step_index < s.agent_max_steps:
                obs = await perceive(page)
                steps_left = s.agent_max_steps - step_index
                t0 = time.perf_counter()
                error: str | None = None
                reasoning = outcome = ""
                action_type = ""
                action_args: dict = {}

                try:
                    decision = await self.planner.plan(goal, obs, history, steps_left)
                    action = decision.action
                    reasoning = decision.reasoning
                    action_type = action.type.value
                    action_args = action.model_dump(exclude_none=True, mode="json")

                    # Reliability gate: detect unproductive loops before executing.
                    nudge = rc.before_action(_dom_hash(obs), action)
                    if nudge:
                        history.append(f"note: {nudge}")

                    result = await rc.execute_with_retry(executor, action, obs)
                    outcome = result.outcome
                    error = result.error
                    if result.ok and action.type is ActionType.FINISH:
                        status = "success" if action.success else "failed"
                        summary = action.summary or ""
                    elif result.terminal:
                        status = "failed" if action.type is ActionType.ASK_USER else status
                        summary = outcome
                except Exception as e:  # noqa: BLE001  -- record and let the planner re-plan
                    error = str(e)
                    outcome = f"step error: {e}"

                # A non-terminal step that errored means the reliability layer kicked in
                # (failed action / caught exception) and the agent will re-plan next step.
                terminal_type = action_type in (ActionType.FINISH.value, ActionType.ASK_USER.value)
                if error and not terminal_type:
                    rc.note_error()

                latency_ms = int((time.perf_counter() - t0) * 1000)
                screenshot_path = await self._screenshot(page, shot_dir, step_index)
                self.repo.add_step(run_id, StepTrace(
                    step_index=step_index,
                    observation_summary=obs.to_prompt()[:2000],
                    reasoning=reasoning,
                    action_type=action_type,
                    action_args=action_args,
                    outcome=outcome,
                    error=error,
                    screenshot_path=screenshot_path,
                    page_url=page.url,
                    dom_hash=_dom_hash(obs),
                    latency_ms=latency_ms,
                ))
                history.append(
                    f"step {step_index}: {action_type or '?'} -> {outcome or error or 'no result'}"
                )
                step_index += 1

                if action_type == ActionType.FINISH.value or (
                    action_type == ActionType.ASK_USER.value
                ):
                    break
                if rc.is_stuck():
                    status, summary = "stuck", "aborted: detected an unproductive loop"
                    break
            else:
                status, summary = "failed", "step budget exhausted"
        except Exception as e:  # noqa: BLE001  -- catastrophic failure
            total_rec = base_recovered + rc.recovered
            self.repo.finish_run(run_id, "failed", step_index, total_rec, error=str(e))
            return RunResult(run_id=run_id, status="failed", steps=step_index,
                             recovered=total_rec, summary=str(e))

        total_rec = base_recovered + rc.recovered
        self.repo.finish_run(run_id, status, step_index, total_rec,
                             error=None if status == "success" else summary)
        return RunResult(run_id=run_id, status=status, steps=step_index,
                         recovered=total_rec, summary=summary)

    async def _screenshot(self, page, shot_dir: Path, idx: int) -> str | None:
        path = shot_dir / f"step_{idx:02d}.png"
        try:
            await page.screenshot(path=str(path))
            return str(path)
        except Exception:  # noqa: BLE001
            return None
