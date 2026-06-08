"""Read-only dashboard: browse runs, inspect per-step traces, view benchmark results.

Reads the same SQLite DB the agent writes to (and the benchmark's latest.json). It
never mutates state — purely observability. Run with:
    uvicorn dashboard.app:app --port 8001
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from web_agent.config import get_settings
from web_agent.storage.repository import Repository

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
RESULTS_DIR = Path(__file__).resolve().parent.parent / "benchmark" / "results"

app = FastAPI(title="Web Agent Dashboard")


def _repo() -> Repository:
    return Repository(get_settings().db_path)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    repo = _repo()
    return TEMPLATES.TemplateResponse(
        request, "index.html", {"runs": repo.list_runs(200), "stats": repo.stats()}
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: int):
    repo = _repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return TEMPLATES.TemplateResponse(
        request, "run.html", {"run": run, "steps": repo.get_steps(run_id)}
    )


@app.get("/benchmark", response_class=HTMLResponse)
def benchmark(request: Request):
    latest = RESULTS_DIR / "latest.json"
    report = json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else None
    return TEMPLATES.TemplateResponse(request, "benchmark.html", {"report": report})


@app.get("/shot/{run_id}/{name}")
def screenshot(run_id: int, name: str):
    # Resolve safely within the configured screenshot dir (no path traversal).
    base = Path(get_settings().screenshot_dir).resolve()
    path = (base / f"run_{run_id}" / Path(name).name).resolve()
    if not str(path).startswith(str(base)) or not path.exists():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(str(path))
