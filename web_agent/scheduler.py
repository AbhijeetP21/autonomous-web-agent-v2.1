"""Recurring runs via APScheduler with a persistent SQLAlchemy jobstore.

Jobs survive process restarts because they live in a SQLite jobstore (separate from
the agent's run-history DB). A job re-invokes :func:`run_scheduled_goal`, which builds
a fresh agent and executes the goal headlessly, persisting a normal run + trace.
"""

from __future__ import annotations

from pathlib import Path

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler


def run_scheduled_goal(goal: str, target: str) -> None:
    """Top-level (picklable) entrypoint a scheduled job calls to run the agent once."""
    import asyncio

    from web_agent.agent import Agent
    from web_agent.config import get_settings
    from web_agent.llm.factory import build_client
    from web_agent.storage.repository import Repository

    settings = get_settings()
    settings.ensure_dirs()
    agent = Agent(build_client(settings), Repository(settings.db_path), settings)
    asyncio.run(agent.run(goal, target))


def jobstore_url(db_path: Path | str) -> str:
    jobs_db = Path(db_path).parent / "scheduler.db"
    jobs_db.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{jobs_db}"


def build_scheduler(db_path: Path | str, blocking: bool = False):
    jobstores = {"default": SQLAlchemyJobStore(url=jobstore_url(db_path))}
    cls = BlockingScheduler if blocking else BackgroundScheduler
    return cls(jobstores=jobstores)


def add_interval_job(scheduler, goal: str, target: str, seconds: int, job_id: str | None = None):
    return scheduler.add_job(
        run_scheduled_goal, "interval", seconds=seconds, args=[goal, target],
        id=job_id, replace_existing=bool(job_id),
    )


def add_cron_job(scheduler, goal: str, target: str, cron: str, job_id: str | None = None):
    """cron is a 5-field expression: 'min hour day month day_of_week'."""
    minute, hour, day, month, dow = cron.split()
    return scheduler.add_job(
        run_scheduled_goal, "cron", args=[goal, target],
        minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
        id=job_id, replace_existing=bool(job_id),
    )
