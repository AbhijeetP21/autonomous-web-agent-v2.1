"""SQLite schema and connection helpers for run state, step traces, and history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    goal         TEXT NOT NULL,
    target_url   TEXT NOT NULL,
    status       TEXT NOT NULL,            -- pending|running|success|failed|stuck|interrupted
    provider     TEXT,
    model        TEXT,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    total_steps  INTEGER NOT NULL DEFAULT 0,
    recovered    INTEGER NOT NULL DEFAULT 0,  -- >=1 if a recovery (retry/replan) fired
    error        TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_index          INTEGER NOT NULL,
    observation_summary TEXT,
    reasoning           TEXT,
    action_type         TEXT,
    action_args         TEXT,             -- JSON
    outcome             TEXT,
    error               TEXT,
    screenshot_path     TEXT,
    page_url            TEXT,
    dom_hash            TEXT,
    latency_ms          INTEGER,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id, step_index);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path | str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
