"""M3 gate: LLM layer returns a valid, whitelisted Action; lenient parsing works."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from web_agent.actions.schema import ActionType, parse_decision
from web_agent.llm.base import LLMClient, loads_lenient


def _has_live_key() -> bool:
    """True if an LLM key is configured via the environment or .env file."""
    try:
        from web_agent.config import Settings

        return bool(Settings().llm_api_key)
    except Exception:  # noqa: BLE001
        return False


class FakeClient(LLMClient):
    """A canned client that mimics a provider returning a take_action payload."""

    def __init__(self, payload: dict):
        super().__init__(model="fake-1")
        self._payload = payload

    async def propose(self, system: str, user: str) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_mocked_client_yields_valid_action():
    client = FakeClient(
        {"reasoning": "type the todo text",
         "action": {"type": "type", "element_id": 2, "text": "buy milk"}}
    )
    raw = await client.propose("sys", "user")
    decision = parse_decision(raw)
    assert decision.action.type is ActionType.TYPE
    assert decision.action.text == "buy milk"
    assert decision.reasoning


@pytest.mark.asyncio
async def test_mocked_client_invalid_action_rejected():
    client = FakeClient({"reasoning": "bad", "action": {"type": "type", "element_id": 2}})  # no txt
    raw = await client.propose("s", "u")
    with pytest.raises(ValidationError):
        parse_decision(raw)


def test_loads_lenient_handles_fenced_json():
    out = loads_lenient('```json\n{"reasoning":"r","action":{"type":"wait","ms":5}}\n```')
    assert out["action"]["type"] == "wait"


@pytest.mark.skipif(not _has_live_key(), reason="no live LLM key configured")
@pytest.mark.asyncio
async def test_live_provider_returns_parseable_action():
    """Optional: with a real key set, the configured provider returns a valid Action."""
    from web_agent.llm.factory import build_client

    client = build_client()
    raw = await client.propose(
        system="You are a web agent. Always call take_action.",
        user=(
            "Goal: add a todo.\nObservation:\n  [1] textbox \"New todo\"\n  [2] button \"Add\"\n"
            "Choose the next action."
        ),
    )
    decision = parse_decision(raw)
    assert decision.action.type in set(ActionType)
