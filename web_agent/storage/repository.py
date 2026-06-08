"""CRUD over runs and step traces (used by the agent, CLI, dashboard, benchmark)."""

from __future__ import annotations

import json
from pathlib import Path

from web_agent.observability.trace import RunRecord, StepTrace, now_iso
from web_agent.storage.db import connect, init_db


class Repository:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        init_db(self.db_path)

    def _conn(self):
        return connect(self.db_path)

    # --- runs ---------------------------------------------------------------
    def create_run(self, goal: str, target_url: str, provider: str, model: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO runs (goal, target_url, status, provider, model, started_at) "
                "VALUES (?, ?, 'running', ?, ?, ?)",
                (goal, target_url, provider, model, now_iso()),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, total_steps: int,
                   recovered: int = 0, error: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE runs SET status=?, ended_at=?, total_steps=?, recovered=?, error=? "
                "WHERE id=?",
                (status, now_iso(), total_steps, recovered, error, run_id),
            )

    def set_status(self, run_id: int, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))

    def get_run(self, run_id: int) -> RunRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return RunRecord(**dict(row)) if row else None

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [RunRecord(**dict(r)) for r in rows]

    # --- steps --------------------------------------------------------------
    def add_step(self, run_id: int, step: StepTrace) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO steps (run_id, step_index, observation_summary, reasoning, "
                "action_type, action_args, outcome, error, screenshot_path, page_url, "
                "dom_hash, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, step.step_index, step.observation_summary, step.reasoning,
                    step.action_type, json.dumps(step.action_args), step.outcome, step.error,
                    step.screenshot_path, step.page_url, step.dom_hash, step.latency_ms,
                    step.created_at,
                ),
            )
            return int(cur.lastrowid)

    def get_steps(self, run_id: int) -> list[StepTrace]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM steps WHERE run_id=? ORDER BY step_index", (run_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["action_args"] = json.loads(d["action_args"]) if d["action_args"] else {}
            out.append(StepTrace(**{k: d[k] for k in StepTrace.model_fields if k in d}))
        return out

    # --- aggregate metrics (dashboard) -------------------------------------
    def stats(self) -> dict:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) total, "
                "SUM(status='success') successes, "
                "SUM(recovered>0) recovered_runs, "
                "AVG(total_steps) avg_steps "
                "FROM runs WHERE status IN ('success','failed','stuck')"
            ).fetchone()
        total = row["total"] or 0
        successes = row["successes"] or 0
        return {
            "total": total,
            "successes": successes,
            "success_rate": (successes / total) if total else 0.0,
            "recovered_runs": row["recovered_runs"] or 0,
            "avg_steps": round(row["avg_steps"], 1) if row["avg_steps"] else 0.0,
        }
