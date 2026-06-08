"""Record a short demo of the agent autonomously completing a sandbox task.

Runs the agent headed with Playwright video capture, then (if ffmpeg is available)
converts the recording to docs/demo.gif for embedding in the README.

Usage (with the sandbox running and .env configured):
    python scripts/record_demo.py \
        --goal "Add 'buy milk' to my todo list and mark it done" \
        --target http://127.0.0.1:8000/todo
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
from pathlib import Path

from web_agent.agent import Agent
from web_agent.config import get_settings
from web_agent.llm.factory import build_client
from web_agent.storage.repository import Repository

DOCS = Path(__file__).resolve().parent.parent / "docs"
VIDEO_DIR = DOCS / "video"


async def _record(goal: str, target: str) -> Path | None:
    from playwright.async_api import async_playwright

    settings = get_settings()
    settings.ensure_dirs()
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    agent = Agent(build_client(settings), Repository(settings.db_path), settings)

    async with async_playwright() as pw:
        # Headless still records the page viewport to video; headed needs an interactive
        # desktop session which isn't always available (CI / sandboxed shells).
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        result = await agent.run(goal, target, page=page)
        print(f"run {result.run_id}: {result.status} in {result.steps} step(s) "
              f"(recoveries: {result.recovered})")
        video_path = await page.video.path() if page.video else None
        await context.close()  # flush the .webm
        await browser.close()
    return Path(video_path) if video_path else None


def _to_gif(webm: Path) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    gif = DOCS / "demo.gif"
    if not ffmpeg:
        print(f"\nffmpeg not found — recording saved at {webm}\n"
              f"Install it (`scoop install ffmpeg`) then run:\n"
              f"  ffmpeg -i {webm} -vf \"fps=12,scale=900:-1:flags=lanczos\" {gif}")
        return None
    palette = DOCS / "palette.png"
    subprocess.run([ffmpeg, "-y", "-i", str(webm),
                    "-vf", "fps=12,scale=900:-1:flags=lanczos,palettegen", str(palette)],
                   check=True)
    subprocess.run([ffmpeg, "-y", "-i", str(webm), "-i", str(palette),
                    "-lavfi", "fps=12,scale=900:-1:flags=lanczos[x];[x][1:v]paletteuse",
                    str(gif)], check=True)
    palette.unlink(missing_ok=True)
    print(f"\nWrote {gif}")
    return gif


def main() -> None:
    p = argparse.ArgumentParser(description="Record a demo GIF of an agent run.")
    p.add_argument("--goal", default="Add 'buy milk' to my todo list and mark it done")
    p.add_argument("--target", default="http://127.0.0.1:8000/todo")
    args = p.parse_args()
    webm = asyncio.run(_record(args.goal, args.target))
    if webm:
        _to_gif(webm)


if __name__ == "__main__":
    main()
