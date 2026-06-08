"""M2 gate: perception + action schema + executor, driven without an LLM."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from web_agent.actions.schema import Action, ActionType, parse_action
from web_agent.executor.playwright_executor import Executor
from web_agent.perception.accessibility import Observation, perceive


def _find(obs: Observation, *, name_contains: str, role: str | None = None) -> int:
    for e in obs.elements:
        if name_contains.lower() in e.name.lower() and (role is None or e.display_role() == role):
            return e.id
    raise AssertionError(
        f"no element matching name~{name_contains!r} role={role} in {obs.to_prompt()}"
    )


@pytest.mark.asyncio
async def test_scripted_add_and_complete_todo(page, sandbox_url):
    await page.goto(f"{sandbox_url}/todo")
    ex = Executor(page, allowed_domains=["127.0.0.1", "localhost"])

    obs = await perceive(page)
    textbox = _find(obs, name_contains="New todo", role="textbox")
    add_btn = _find(obs, name_contains="Add", role="button")

    r1 = await ex.execute(Action(type=ActionType.TYPE, element_id=textbox, text="buy milk"), obs)
    assert r1.ok, r1.error
    r2 = await ex.execute(Action(type=ActionType.CLICK, element_id=add_btn), obs)
    assert r2.ok, r2.error

    obs2 = await perceive(page)
    done_btn = _find(obs2, name_contains="buy milk")  # the "Mark ... done" button
    r3 = await ex.execute(Action(type=ActionType.CLICK, element_id=done_btn), obs2)
    assert r3.ok, r3.error

    status = await page.locator("#todo-list li").first.get_attribute("data-status")
    assert status == "done"


@pytest.mark.asyncio
async def test_finish_action_is_terminal(page, sandbox_url):
    await page.goto(f"{sandbox_url}/todo")
    ex = Executor(page, allowed_domains=["127.0.0.1"])
    obs = await perceive(page)
    res = await ex.execute(Action(type=ActionType.FINISH, success=True, summary="done"), obs)
    assert res.terminal and res.ok


@pytest.mark.asyncio
async def test_invalid_element_id_is_rejected(page, sandbox_url):
    await page.goto(f"{sandbox_url}/todo")
    ex = Executor(page, allowed_domains=["127.0.0.1"])
    obs = await perceive(page)
    with pytest.raises(KeyError):
        await ex.execute(Action(type=ActionType.CLICK, element_id=9999), obs)


@pytest.mark.asyncio
async def test_navigation_domain_allowlist(page, sandbox_url):
    await page.goto(f"{sandbox_url}/todo")
    ex = Executor(page, allowed_domains=["127.0.0.1", "localhost"])
    obs = await perceive(page)
    nav = Action(type=ActionType.NAVIGATE, url="https://evil.example.com")
    blocked = await ex.execute(nav, obs)
    assert not blocked.ok and blocked.error == "domain_blocked"


def test_bad_actions_are_rejected():
    # Unknown action type.
    with pytest.raises(ValidationError):
        parse_action({"type": "explode"})
    # Missing required field for the type.
    with pytest.raises(ValidationError):
        parse_action({"type": "type", "element_id": 1})  # no text
    with pytest.raises(ValidationError):
        parse_action({"type": "navigate"})  # no url
    # Valid one parses.
    a = parse_action({"type": "wait", "ms": 50})
    assert a.type is ActionType.WAIT
