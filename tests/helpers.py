"""Shared test utilities: a scripted (no-LLM) client and element-id resolution."""

from __future__ import annotations

import re

from web_agent.llm.base import LLMClient


def find_element_id(prompt: str, name_contains: str) -> int:
    """Resolve an element id from the rendered observation text by accessible name."""
    for m in re.finditer(r'\[(\d+)\]\s+\S+\s+"([^"]*)"', prompt):
        if name_contains.lower() in m.group(2).lower():
            return int(m.group(1))
    raise AssertionError(f"no element with name~{name_contains!r} in prompt:\n{prompt}")


class ScriptedClient(LLMClient):
    """Returns a fixed sequence of (action_type, name_or_None, extra) decisions.

    When ``name`` is given, the element id is resolved from the observation text;
    otherwise ``extra`` may carry an explicit ``element_id`` (e.g. to force a bad one).
    """

    def __init__(self, script: list[tuple]):
        super().__init__(model="scripted")
        self.script = script
        self.i = 0

    async def propose(self, system: str, user: str) -> dict:
        kind, name, extra = self.script[self.i]
        self.i += 1
        action = {"type": kind, **extra}
        if name is not None:
            action["element_id"] = find_element_id(user, name)
        return {"reasoning": f"scripted step {self.i}", "action": action}


class LoopingClient(LLMClient):
    """Always returns the same action (used to trip loop detection)."""

    def __init__(self, action: dict):
        super().__init__(model="looping")
        self._action = action

    async def propose(self, system: str, user: str) -> dict:
        return {"reasoning": "stuck", "action": dict(self._action)}


class NeverFinishClient(LLMClient):
    """Types a distinct value each step so the page changes but the goal never ends."""

    def __init__(self, target_name: str = "New todo"):
        super().__init__(model="never-finish")
        self.target_name = target_name
        self.i = 0

    async def propose(self, system: str, user: str) -> dict:
        eid = find_element_id(user, self.target_name)
        self.i += 1
        return {
            "reasoning": "keep typing",
            "action": {"type": "type", "element_id": eid, "text": f"item {self.i}"},
        }
