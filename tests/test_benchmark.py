"""M7 gate: the benchmark runs N iterations and emits a success/steps/recovery report."""

from __future__ import annotations

import json

import pytest
from helpers import ScriptedClient

from benchmark.run_benchmark import render_markdown, run_benchmark, write_report
from web_agent.config import Settings


def _todo_client() -> ScriptedClient:
    return ScriptedClient([
        ("type", "New todo", {"text": "buy milk"}),
        ("click", "Add", {}),
        ("click", "buy milk", {}),
        ("finish", None, {"success": True, "summary": "done"}),
    ])


@pytest.mark.asyncio
async def test_benchmark_runs_and_reports(sandbox_url, tmp_path):
    settings = Settings(
        db_path=tmp_path / "agent.db",
        screenshot_dir=tmp_path / "shots",
        agent_domain_allowlist="127.0.0.1,localhost",
    )
    report = await run_benchmark(
        runs=2,
        base_url=sandbox_url,
        include_public=False,
        only=["todo_add_complete"],
        make_client=_todo_client,
        settings=settings,
    )

    assert report["runs_per_task"] == 2
    assert len(report["tasks"]) == 1
    m = report["tasks"][0]["metrics"]
    assert m["runs"] == 2 and m["successes"] == 2 and m["success_rate"] == 1.0
    assert report["overall"]["success_rate"] == 1.0

    # Report files are written (json + markdown + latest pointers).
    json_path, md_path = write_report(report, out_dir=tmp_path / "results")
    assert json_path.exists() and md_path.exists()
    assert (tmp_path / "results" / "latest.json").exists()
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["overall"]["successes"] == 2
    assert "Benchmark Report" in render_markdown(report)
