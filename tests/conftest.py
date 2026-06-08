"""Shared test fixtures: a live sandbox server and a Playwright page."""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import httpx
import pytest
import pytest_asyncio


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def sandbox_url() -> str:
    """Launch the local sandbox server as a subprocess; yield its base URL."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "sandbox.server"],
        env={"SANDBOX_PORT": str(port), **_inherit_env()},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_until_up(base)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _inherit_env() -> dict:
    import os

    return dict(os.environ)


def _wait_until_up(base: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            if httpx.get(base, timeout=1.0).status_code == 200:
                return
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.2)
    raise RuntimeError(f"sandbox server did not start at {base}: {last_err}")


@pytest_asyncio.fixture
async def page(sandbox_url):
    """A fresh Playwright page (headless Chromium) per test."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        pg = await context.new_page()
        try:
            yield pg
        finally:
            await context.close()
            await browser.close()
