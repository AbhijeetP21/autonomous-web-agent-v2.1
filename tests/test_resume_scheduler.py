"""M6 gate: interrupted runs resume and finish; scheduled jobs persist and fire."""

from __future__ import annotations

import time

import pytest
from helpers import ScriptedClient

from web_agent.agent import Agent
from web_agent.config import Settings
from web_agent.observability.trace import StepTrace
from web_agent.scheduler import add_interval_job, build_scheduler, run_scheduled_goal
from web_agent.storage.repository import Repository


def _settings(tmp_path, **over):
    return Settings(
        db_path=tmp_path / "agent.db",
        screenshot_dir=tmp_path / "shots",
        agent_domain_allowlist="127.0.0.1,localhost",
        **over,
    )


@pytest.mark.asyncio
async def test_resume_interrupted_run_finishes(page, sandbox_url, tmp_path):
    s = _settings(tmp_path)
    s.ensure_dirs()
    repo = Repository(s.db_path)

    # Simulate a run that was interrupted after one recorded step (still 'running').
    run_id = repo.create_run("Add 'buy milk' and mark it done", f"{sandbox_url}/todo",
                             s.llm_provider, s.llm_model)
    repo.add_step(run_id, StepTrace(step_index=0, action_type="navigate",
                                    outcome="opened todo page", page_url=f"{sandbox_url}/todo",
                                    dom_hash="seed"))

    client = ScriptedClient([
        ("type", "New todo", {"text": "buy milk"}),
        ("click", "Add", {}),
        ("click", "buy milk", {}),
        ("finish", None, {"success": True, "summary": "resumed and completed"}),
    ])
    result = await Agent(client, repo, s).resume(run_id, page=page)

    assert result.status == "success"
    run = repo.get_run(run_id)
    assert run.status == "success" and run.total_steps == 5  # 1 prior + 4 resumed
    steps = repo.get_steps(run_id)
    assert [st.step_index for st in steps] == [0, 1, 2, 3, 4]
    assert await page.locator('#todo-list li[data-status="done"]').count() == 1


def test_scheduled_jobs_persist_across_restart(tmp_path):
    s = _settings(tmp_path)
    # start(paused=True) flushes added jobs to the persistent store without firing them.
    sched1 = build_scheduler(s.db_path)
    sched1.start(paused=True)
    add_interval_job(sched1, "ping", "http://127.0.0.1/todo", seconds=3600, job_id="job-a")
    assert sched1.get_job("job-a") is not None
    sched1.shutdown(wait=False)

    # A brand-new scheduler reading the same persistent store still sees the job.
    sched2 = build_scheduler(s.db_path)
    sched2.start(paused=True)
    try:
        assert sched2.get_job("job-a") is not None
    finally:
        sched2.shutdown(wait=False)


def test_scheduler_fires_and_persists_a_run(sandbox_url, tmp_path, monkeypatch):
    """A due job invokes the agent (with a scripted client) and a run lands in the DB."""
    s = _settings(tmp_path)
    s.ensure_dirs()

    # Make the scheduled entrypoint use our settings + a scripted client (no live LLM).
    monkeypatch.setattr("web_agent.config.get_settings", lambda: s)
    client = ScriptedClient([
        ("type", "New todo", {"text": "scheduled milk"}),
        ("click", "Add", {}),
        ("finish", None, {"success": True, "summary": "scheduled run done"}),
    ])
    monkeypatch.setattr("web_agent.llm.factory.build_client", lambda *a, **k: client)

    sched = build_scheduler(s.db_path)
    sched.add_job(run_scheduled_goal, "date", args=["add todo", f"{sandbox_url}/todo"])
    sched.start()
    try:
        repo = Repository(s.db_path)
        deadline = time.time() + 30
        runs = []
        while time.time() < deadline:
            runs = repo.list_runs()
            if runs and runs[0].status in ("success", "failed", "stuck"):
                break
            time.sleep(0.3)
    finally:
        sched.shutdown(wait=False)

    assert runs and runs[0].status == "success"
