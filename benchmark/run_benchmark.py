"""Benchmark harness: run each task N times and measure reliability.

Metrics (the senior signal): per-task and overall **task success rate**,
**mean steps-to-completion**, and **recovery rate** (of the runs where the reliability
layer fired, how many still succeeded). Success is judged by an independent check on
the final page — not the agent's self-report.

Usage:  python -m benchmark.run_benchmark --runs 5 [--include-public] [--only todo_add_complete]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from benchmark.checks import evaluate_check
from web_agent.agent import Agent
from web_agent.browser import browser_page
from web_agent.config import Settings, get_settings
from web_agent.storage.repository import Repository

TASKS_PATH = Path(__file__).parent / "tasks.yaml"
RESULTS_DIR = Path(__file__).parent / "results"


def load_tasks(
    path: Path, base_url: str, include_public: bool, only: list[str] | None
) -> list[dict]:
    tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for t in tasks:
        if only and t["id"] not in only:
            continue
        if t.get("public") and not include_public:
            continue
        t = dict(t)
        t["target"] = t["target"].replace("{base}", base_url.rstrip("/"))
        t["goal"] = " ".join(t["goal"].split())  # collapse YAML folded whitespace
        out.append(t)
    return out


async def _run_single(task: dict, make_client, settings: Settings, repo: Repository) -> dict:
    async with browser_page(headless=settings.agent_headless) as page:
        agent = Agent(make_client(), repo, settings)
        result = await agent.run(task["goal"], task["target"], page=page)
        try:
            passed = await evaluate_check(page, task["success_check"])
        except Exception:  # noqa: BLE001  -- a broken page still counts as a failure
            passed = False
    return {
        "run_id": result.run_id,
        "success": passed,
        "agent_status": result.status,
        "steps": result.steps,
        "recovered": result.recovered,
    }


def _aggregate(records: list[dict]) -> dict:
    n = len(records)
    successes = [r for r in records if r["success"]]
    triggered = [r for r in records if r["recovered"] > 0]
    recovered_ok = [r for r in triggered if r["success"]]
    mean_steps = round(sum(r["steps"] for r in successes) / len(successes), 1) if successes else 0.0
    return {
        "runs": n,
        "successes": len(successes),
        "success_rate": round(len(successes) / n, 3) if n else 0.0,
        "mean_steps_on_success": mean_steps,
        "recovery_triggered": len(triggered),
        "recovery_success_rate": (
            round(len(recovered_ok) / len(triggered), 3) if triggered else None
        ),
    }


async def run_benchmark(runs: int, base_url: str, include_public: bool,
                        only: list[str] | None, make_client, settings: Settings) -> dict:
    settings.ensure_dirs()
    repo = Repository(settings.db_path)
    tasks = load_tasks(TASKS_PATH, base_url, include_public, only)
    per_task = []
    for task in tasks:
        records = []
        for i in range(runs):
            print(f"  [{task['id']}] run {i + 1}/{runs} …", flush=True)
            records.append(await _run_single(task, make_client, settings, repo))
        agg = _aggregate(records)
        per_task.append({"id": task["id"], "description": task["description"],
                         "metrics": agg, "records": records})

    overall = _aggregate([r for t in per_task for r in t["records"]])
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "runs_per_task": runs,
        "overall": overall,
        "tasks": per_task,
    }


def render_markdown(report: dict) -> str:
    o = report["overall"]
    lines = [
        f"# Benchmark Report — {report['generated_at']}",
        "",
        f"- Provider/model: `{report['provider']}` / `{report['model']}`",
        f"- Runs per task: **{report['runs_per_task']}**",
        "",
        "| Task | Success rate | Mean steps | Recovery fired | Recovery success |",
        "|------|--------------|-----------|----------------|------------------|",
    ]
    for t in report["tasks"]:
        m = t["metrics"]
        rsr = "—" if m["recovery_success_rate"] is None else f"{m['recovery_success_rate']:.0%}"
        lines.append(
            f"| {t['id']} | {m['success_rate']:.0%} ({m['successes']}/{m['runs']}) "
            f"| {m['mean_steps_on_success']} | {m['recovery_triggered']} | {rsr} |"
        )
    orsr = "—" if o["recovery_success_rate"] is None else f"{o['recovery_success_rate']:.0%}"
    lines += [
        "",
        f"**Overall:** success {o['successes']}/{o['runs']} "
        f"({o['success_rate']:.0%}), mean steps {o['mean_steps_on_success']}, "
        f"recovery fired in {o['recovery_triggered']} run(s), recovery success {orsr}.",
        "",
    ]
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path = RESULTS_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("-", "")[:15]
    json_path = out_dir / f"benchmark_{stamp}.json"
    md_path = out_dir / f"benchmark_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    # Stable "latest" pointers for the dashboard.
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "latest.md").write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    p = argparse.ArgumentParser(description="Run the autonomous web agent benchmark.")
    p.add_argument("--runs", type=int, default=5, help="Iterations per task.")
    p.add_argument("--base", default=None, help="Local sandbox base URL.")
    p.add_argument("--include-public", action="store_true", help="Also run saucedemo tasks.")
    p.add_argument("--only", nargs="*", default=None, help="Only these task ids.")
    args = p.parse_args()

    settings = get_settings()
    base = args.base or f"http://127.0.0.1:{settings.sandbox_port}"
    from web_agent.llm.factory import build_client

    report = asyncio.run(run_benchmark(
        runs=args.runs, base_url=base, include_public=args.include_public,
        only=args.only, make_client=lambda: build_client(settings), settings=settings,
    ))
    json_path, md_path = write_report(report)
    print("\n" + render_markdown(report))
    print(f"Wrote {json_path}\n      {md_path}")


if __name__ == "__main__":
    main()
