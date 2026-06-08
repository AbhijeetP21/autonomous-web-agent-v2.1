"""Capture dashboard screenshots into docs/ for the README. Dashboard must be running."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"


async def main(base: str) -> None:
    from playwright.async_api import async_playwright

    DOCS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1100, "height": 900})
        await page.goto(f"{base}/", wait_until="networkidle")
        await page.screenshot(path=str(DOCS / "dashboard.png"))
        await page.goto(f"{base}/runs/1", wait_until="networkidle")
        await page.screenshot(path=str(DOCS / "run_trace.png"), full_page=True)
        await page.goto(f"{base}/benchmark", wait_until="networkidle")
        await page.screenshot(path=str(DOCS / "benchmark.png"))
        await browser.close()
    print(f"wrote dashboard.png, run_trace.png, benchmark.png to {DOCS}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"))
