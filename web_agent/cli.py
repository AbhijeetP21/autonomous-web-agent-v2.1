"""Command-line entrypoint: run goals, list runs, inspect traces."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from web_agent.agent import Agent
from web_agent.config import get_settings
from web_agent.llm.factory import build_client
from web_agent.storage.repository import Repository

app = typer.Typer(add_completion=False, help="Autonomous web agent CLI.")
console = Console()

_STATUS_COLOR = {
    "success": "green", "failed": "red", "stuck": "yellow",
    "running": "cyan", "interrupted": "magenta",
}


def _repo() -> Repository:
    return Repository(get_settings().db_path)


@app.command()
def run(
    goal: str = typer.Argument(..., help="The high-level goal for the agent."),
    target: str = typer.Option(..., "--target", "-t", help="Starting URL."),
):
    """Run the agent against TARGET to accomplish GOAL."""
    settings = get_settings()
    settings.ensure_dirs()
    client = build_client(settings)
    agent = Agent(client, _repo(), settings)
    console.print(f"[bold]Goal:[/bold] {goal}\n[bold]Target:[/bold] {target}\n"
                  f"[dim]{client.label}, max_steps={settings.agent_max_steps}[/dim]")
    result = asyncio.run(agent.run(goal, target))
    color = _STATUS_COLOR.get(result.status, "white")
    console.print(
        f"\n[bold {color}]{result.status.upper()}[/bold {color}] in {result.steps} step(s)"
        f" (recoveries: {result.recovered})\nrun_id={result.run_id} — {result.summary}"
    )
    console.print(f"[dim]Inspect: web-agent show {result.run_id}[/dim]")


@app.command(name="list")
def list_runs(limit: int = typer.Option(20, help="Max rows.")):
    """List recent runs."""
    rows = _repo().list_runs(limit)
    table = Table(title="Runs")
    for col in ("id", "status", "steps", "rec", "goal", "started"):
        table.add_column(col)
    for r in rows:
        color = _STATUS_COLOR.get(r.status, "white")
        table.add_row(str(r.id), f"[{color}]{r.status}[/{color}]", str(r.total_steps),
                      str(r.recovered), r.goal[:50], (r.started_at or "")[:19])
    console.print(table)


@app.command()
def resume(run_id: int = typer.Argument(..., help="Id of an interrupted/running run.")):
    """Resume an interrupted run from its last recorded step."""
    settings = get_settings()
    settings.ensure_dirs()
    agent = Agent(build_client(settings), _repo(), settings)
    result = asyncio.run(agent.resume(run_id))
    color = _STATUS_COLOR.get(result.status, "white")
    console.print(f"[bold {color}]{result.status.upper()}[/bold {color}] "
                  f"(run {result.run_id}, {result.steps} total steps) — {result.summary}")


@app.command()
def schedule(
    goal: str = typer.Argument(...),
    target: str = typer.Option(..., "--target", "-t"),
    every: int = typer.Option(0, help="Interval in seconds (use this OR --cron)."),
    cron: str = typer.Option("", help="5-field cron: 'min hour day month dow'."),
    job_id: str = typer.Option("", help="Stable id (lets you replace the job later)."),
):
    """Register a recurring run in the persistent scheduler store."""
    from web_agent.scheduler import add_cron_job, add_interval_job, build_scheduler

    settings = get_settings()
    sched = build_scheduler(settings.db_path)
    jid = job_id or None
    if cron:
        job = add_cron_job(sched, goal, target, cron, jid)
    elif every > 0:
        job = add_interval_job(sched, goal, target, every, jid)
    else:
        console.print("[red]Provide --every SECONDS or --cron EXPR[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Scheduled[/green] job {job.id}: {goal!r} @ {target}")
    console.print("[dim]Start the worker with: web-agent serve-scheduler[/dim]")


@app.command(name="schedules")
def list_schedules():
    """List registered scheduled jobs."""
    from web_agent.scheduler import build_scheduler

    sched = build_scheduler(get_settings().db_path)
    table = Table(title="Scheduled jobs")
    for col in ("id", "next run", "trigger"):
        table.add_column(col)
    for job in sched.get_jobs():
        table.add_row(job.id, str(job.next_run_time), str(job.trigger))
    console.print(table)


@app.command(name="serve-scheduler")
def serve_scheduler():
    """Run the scheduler in the foreground, executing jobs as they come due."""
    from web_agent.scheduler import build_scheduler

    sched = build_scheduler(get_settings().db_path, blocking=True)
    console.print("[bold]Scheduler running[/bold] (Ctrl+C to stop)…")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("stopped")


@app.command()
def show(run_id: int = typer.Argument(...)):
    """Show the full step-by-step trace for a run."""
    repo = _repo()
    run = repo.get_run(run_id)
    if not run:
        console.print(f"[red]No run {run_id}[/red]")
        raise typer.Exit(1)
    color = _STATUS_COLOR.get(run.status, "white")
    console.print(f"[bold]Run {run.id}[/bold]  [{color}]{run.status}[/{color}]  "
                  f"steps={run.total_steps} recoveries={run.recovered}")
    console.print(f"[dim]{run.goal} @ {run.target_url}[/dim]\n")
    for s in repo.get_steps(run_id):
        console.print(f"[bold cyan]#{s.step_index}[/bold cyan] {s.action_type} "
                      f"[dim]({s.latency_ms}ms)[/dim]")
        if s.reasoning:
            console.print(f"  reasoning: {s.reasoning}")
        console.print(f"  outcome: {s.outcome}")
        if s.error:
            console.print(f"  [red]error: {s.error}[/red]")


if __name__ == "__main__":
    app()
