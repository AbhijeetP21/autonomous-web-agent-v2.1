"""M4 gate: the full perceive->plan->act->record loop completes a task and persists.

Uses a ScriptedClient (resolving element ids from the observation text) instead of a
live LLM, so the loop wiring + storage are verified deterministically and offline.
The live-LLM autonomy is exercised separately via the CLI.
"""

from __future__ import annotations

import pytest
from helpers import ScriptedClient

from web_agent.agent import Agent
from web_agent.config import Settings
from web_agent.storage.repository import Repository


@pytest.mark.asyncio
async def test_agent_completes_todo_and_persists(page, sandbox_url, tmp_path):
    settings = Settings(
        db_path=tmp_path / "agent.db",
        screenshot_dir=tmp_path / "shots",
        llm_provider="anthropic",
        llm_model="scripted",
        agent_domain_allowlist="127.0.0.1,localhost",
    )
    settings.ensure_dirs()
    repo = Repository(settings.db_path)

    client = ScriptedClient([
        ("type", "New todo", {"text": "buy milk"}),
        ("click", "Add", {}),
        ("click", "buy milk", {}),  # the "Mark 'buy milk' done" button
        ("finish", None, {"success": True, "summary": "added and completed"}),
    ])
    agent = Agent(client, repo, settings)

    result = await agent.run("Add 'buy milk' and mark it done", f"{sandbox_url}/todo", page=page)

    assert result.status == "success", result.summary
    # Independent check: the item is actually marked done in the DOM.
    assert await page.locator('#todo-list li[data-status="done"]').count() == 1

    # Persistence: run + per-step traces are stored.
    run = repo.get_run(result.run_id)
    assert run and run.status == "success" and run.total_steps == 4
    steps = repo.get_steps(result.run_id)
    assert [s.action_type for s in steps] == ["type", "click", "click", "finish"]
    assert all(s.dom_hash for s in steps)
    assert steps[0].screenshot_path  # screenshots captured
