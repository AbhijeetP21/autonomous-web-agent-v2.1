"""Populate the run-history DB with a few real agent executions (no LLM key needed).

These are genuine perceive->act->record runs against the local sandbox, driven by a
scripted policy instead of an LLM — useful for exercising the dashboard end-to-end.
Requires the sandbox to be running (default http://127.0.0.1:8000).

    python scripts/seed_demo.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import asyncio
import re

from web_agent.agent import Agent
from web_agent.config import get_settings
from web_agent.llm.base import LLMClient
from web_agent.storage.repository import Repository


def _find_id(prompt: str, name: str) -> int:
    for m in re.finditer(r'\[(\d+)\]\s+\S+\s+"([^"]*)"', prompt):
        if name.lower() in m.group(2).lower():
            return int(m.group(1))
    raise AssertionError(f"no element ~{name!r}")


class Scripted(LLMClient):
    def __init__(self, script):
        super().__init__(model="scripted-demo")
        self.script, self.i = script, 0

    async def propose(self, system, user):
        kind, name, extra = self.script[self.i]
        self.i += 1
        action = {"type": kind, **extra}
        if name is not None:
            action["element_id"] = _find_id(user, name)
        return {"reasoning": f"scripted step {self.i}", "action": action}


class Looping(LLMClient):
    async def propose(self, system, user):
        return {"reasoning": "no progress", "action": {"type": "wait", "ms": 10}}


async def main(base: str) -> None:
    s = get_settings()
    s.ensure_dirs()
    repo = Repository(s.db_path)

    # 1) Todo task that succeeds.
    todo = Scripted([
        ("type", "New todo", {"text": "buy milk"}),
        ("click", "Add", {}),
        ("click", "buy milk", {}),
        ("finish", None, {"success": True, "summary": "added and completed the todo"}),
    ])
    await Agent(todo, repo, s).run("Add 'buy milk' and mark it done", f"{base}/todo")

    # 2) Login flow that recovers from a bad first action, then succeeds.
    login = Scripted([
        ("click", None, {"element_id": 9999}),  # bad element -> recovery
        ("type", "Username", {"text": "standard_user"}),
        ("type", "Password", {"text": "secret_sauce"}),
        ("click", "Login", {}),
        ("finish", None, {"success": True, "summary": "logged in and reached dashboard"}),
    ])
    await Agent(login, repo, s).run("Log in and reach the dashboard", f"{base}/login")

    # 3) A run that loops and aborts as 'stuck' (shows the reliability layer working).
    await Agent(Looping(model="looping"), repo, s).run("Demonstrate loop abort", f"{base}/todo")

    print("Seeded 3 runs. Start the dashboard: mise run dashboard")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    asyncio.run(main(p.parse_args().base))
