"""Playwright browser lifecycle helper."""

from __future__ import annotations

from contextlib import asynccontextmanager


@asynccontextmanager
async def browser_page(headless: bool = True):
    """Yield a fresh Chromium page, tearing everything down on exit."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()
