"""Structured per-step trace records (the observability layer's unit of record)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StepTrace(BaseModel):
    step_index: int
    observation_summary: str = ""
    reasoning: str = ""
    action_type: str = ""
    action_args: dict = Field(default_factory=dict)
    outcome: str = ""
    error: str | None = None
    screenshot_path: str | None = None
    page_url: str = ""
    dom_hash: str = ""
    latency_ms: int = 0
    created_at: str = Field(default_factory=now_iso)


class RunRecord(BaseModel):
    id: int
    goal: str
    target_url: str
    status: str
    provider: str | None = None
    model: str | None = None
    started_at: str
    ended_at: str | None = None
    total_steps: int = 0
    recovered: int = 0
    error: str | None = None
