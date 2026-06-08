"""M8 gate: the read-only dashboard renders runs, a trace with screenshots, and stats."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from dashboard import app as dash
from web_agent.config import Settings
from web_agent.observability.trace import StepTrace
from web_agent.storage.repository import Repository


def _seed(tmp_path):
    settings = Settings(db_path=tmp_path / "agent.db", screenshot_dir=tmp_path / "shots")
    settings.ensure_dirs()
    repo = Repository(settings.db_path)
    run_id = repo.create_run("Add 'buy milk' and mark it done",
                             "http://127.0.0.1/todo", "anthropic", "MiniMax-M3")
    shot_dir = settings.screenshot_dir / f"run_{run_id}"
    shot_dir.mkdir(parents=True, exist_ok=True)
    (shot_dir / "step_00.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal stub
    repo.add_step(run_id, StepTrace(
        step_index=0, action_type="type", reasoning="enter the todo text",
        action_args={"type": "type", "element_id": 5, "text": "buy milk"},
        outcome="typed into element [5]", screenshot_path=str(shot_dir / "step_00.png"),
        page_url="http://127.0.0.1/todo", dom_hash="abc", latency_ms=42,
    ))
    repo.finish_run(run_id, "success", total_steps=1, recovered=0)
    return settings, run_id


def test_dashboard_renders(tmp_path, monkeypatch):
    settings, run_id = _seed(tmp_path)
    monkeypatch.setattr(dash, "get_settings", lambda: settings)
    client = TestClient(dash.app)

    # Runs list with aggregate success rate.
    r = client.get("/")
    assert r.status_code == 200
    assert "buy milk" in r.text and "100%" in r.text

    # Run detail trace with reasoning + screenshot reference.
    rd = client.get(f"/runs/{run_id}")
    assert rd.status_code == 200
    assert "enter the todo text" in rd.text
    assert f"/shot/{run_id}/step_00.png" in rd.text

    # Screenshot is served.
    shot = client.get(f"/shot/{run_id}/step_00.png")
    assert shot.status_code == 200

    # Missing run -> 404.
    assert client.get("/runs/99999").status_code == 404


def test_dashboard_benchmark_view(tmp_path, monkeypatch):
    settings, _ = _seed(tmp_path)
    monkeypatch.setattr(dash, "get_settings", lambda: settings)
    results = tmp_path / "results"
    results.mkdir()
    (results / "latest.json").write_text(json.dumps({
        "generated_at": "2026-06-08T00:00:00+00:00", "provider": "anthropic",
        "model": "MiniMax-M3", "runs_per_task": 3,
        "overall": {"runs": 3, "successes": 3, "success_rate": 1.0,
                    "mean_steps_on_success": 4.0, "recovery_triggered": 1,
                    "recovery_success_rate": 1.0},
        "tasks": [{"id": "todo_add_complete", "description": "Add a todo",
                   "metrics": {"runs": 3, "successes": 3, "success_rate": 1.0,
                               "mean_steps_on_success": 4.0, "recovery_triggered": 1,
                               "recovery_success_rate": 1.0}}],
    }), encoding="utf-8")
    monkeypatch.setattr(dash, "RESULTS_DIR", results)

    r = TestClient(dash.app).get("/benchmark")
    assert r.status_code == 200
    assert "todo_add_complete" in r.text and "100%" in r.text
