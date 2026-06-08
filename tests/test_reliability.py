"""M5 gate: retry/backoff recovers, loops break to 'stuck', step budget is enforced."""

from __future__ import annotations

import pytest
from helpers import LoopingClient, NeverFinishClient, ScriptedClient
from playwright.async_api import TimeoutError as PWTimeout

from web_agent.actions.schema import Action, ActionType
from web_agent.agent import Agent
from web_agent.config import Settings
from web_agent.executor.playwright_executor import ActionResult
from web_agent.reliability.controller import ReliabilityController
from web_agent.storage.repository import Repository


class FlakyExecutor:
    """Raises a transient Playwright error N times, then succeeds."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def execute(self, action, obs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise PWTimeout("locator timeout (simulated)")
        return ActionResult(ok=True, outcome="ok after retries")


# --- unit: retry / backoff --------------------------------------------------
@pytest.mark.asyncio
async def test_retry_recovers_from_transient_error():
    rc = ReliabilityController(retry_max=3, base_backoff=0.0)
    ex = FlakyExecutor(fail_times=2)
    res = await rc.execute_with_retry(ex, Action(type=ActionType.CLICK, element_id=1), obs=None)
    assert res.ok and ex.calls == 3 and rc.recovered == 2


@pytest.mark.asyncio
async def test_retry_gives_up_after_max():
    rc = ReliabilityController(retry_max=2, base_backoff=0.0)
    ex = FlakyExecutor(fail_times=99)
    res = await rc.execute_with_retry(ex, Action(type=ActionType.CLICK, element_id=1), obs=None)
    assert not res.ok and res.error == "playwright_error"


@pytest.mark.asyncio
async def test_bad_element_is_not_retried():
    class BadExecutor:
        async def execute(self, action, obs):
            raise KeyError("element_id 9999 not in observation")

    rc = ReliabilityController()
    bad = Action(type=ActionType.CLICK, element_id=9999)
    res = await rc.execute_with_retry(BadExecutor(), bad, None)
    assert not res.ok and res.error == "bad_element"


# --- unit: loop detection ---------------------------------------------------
def test_loop_detection_trips_to_stuck():
    rc = ReliabilityController(loop_window=3)
    act = Action(type=ActionType.WAIT, ms=10)
    assert rc.before_action("hashA", act) is None          # 1st
    assert rc.before_action("hashA", act) is not None       # 2nd: nudge
    assert not rc.is_stuck()
    assert rc.before_action("hashA", act) is not None       # 3rd: stuck
    assert rc.is_stuck()


def test_changing_state_does_not_trip_loop():
    rc = ReliabilityController(loop_window=3)
    act = Action(type=ActionType.WAIT, ms=10)
    for h in ("a", "b", "c", "d"):
        rc.before_action(h, act)  # different dom_hash each time
    assert not rc.is_stuck()


# --- integration: through the real agent + sandbox --------------------------
def _settings(tmp_path, **over):
    return Settings(
        db_path=tmp_path / "agent.db",
        screenshot_dir=tmp_path / "shots",
        agent_domain_allowlist="127.0.0.1,localhost",
        **over,
    )


@pytest.mark.asyncio
async def test_agent_recovers_from_bad_action_then_succeeds(page, sandbox_url, tmp_path):
    s = _settings(tmp_path)
    s.ensure_dirs()
    repo = Repository(s.db_path)
    client = ScriptedClient([
        ("click", None, {"element_id": 9999}),          # forced bad element -> recovered
        ("type", "New todo", {"text": "buy milk"}),
        ("click", "Add", {}),
        ("click", "buy milk", {}),
        ("finish", None, {"success": True, "summary": "done after recovery"}),
    ])
    result = await Agent(client, repo, s).run("add todo", f"{sandbox_url}/todo", page=page)
    assert result.status == "success"
    assert result.recovered >= 1
    assert await page.locator('#todo-list li[data-status="done"]').count() == 1


@pytest.mark.asyncio
async def test_agent_aborts_on_loop(page, sandbox_url, tmp_path):
    s = _settings(tmp_path, agent_loop_window=3, agent_max_steps=10)
    s.ensure_dirs()
    repo = Repository(s.db_path)
    client = LoopingClient({"type": "wait", "ms": 10})
    result = await Agent(client, repo, s).run("loop forever", f"{sandbox_url}/todo", page=page)
    assert result.status == "stuck"
    assert result.steps <= 3  # broke out promptly, did not spiral


@pytest.mark.asyncio
async def test_step_budget_is_enforced(page, sandbox_url, tmp_path):
    s = _settings(tmp_path, agent_max_steps=3)
    s.ensure_dirs()
    repo = Repository(s.db_path)
    client = NeverFinishClient(target_name="New todo")
    result = await Agent(client, repo, s).run("never ends", f"{sandbox_url}/todo", page=page)
    assert result.status == "failed"
    assert result.steps == 3
    assert "budget" in result.summary
