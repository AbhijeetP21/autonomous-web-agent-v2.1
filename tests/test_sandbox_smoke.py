"""M1 gate: every sandbox flow loads and can be clicked through with Playwright."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_todo_flow(page, sandbox_url):
    await page.goto(f"{sandbox_url}/todo")
    await page.fill("#new-todo", "buy milk")
    await page.click("#add-todo")
    item = page.locator("#todo-list li").first
    await item.wait_for()
    assert await item.get_attribute("data-status") == "pending"
    await item.get_by_role("button", name="Mark \"buy milk\" done").click()
    assert await item.get_attribute("data-status") == "done"


@pytest.mark.asyncio
async def test_checkout_flow(page, sandbox_url):
    await page.goto(f"{sandbox_url}/shop")
    await page.get_by_role("button", name="Checkout").click()
    # Shipping
    await page.fill("#full_name", "Ada Lovelace")
    await page.fill("#address", "1 Analytical Engine Way")
    await page.get_by_role("button", name="Continue to payment").click()
    # Payment
    await page.fill("#card_number", "4111111111111111")
    await page.fill("#card_name", "Ada Lovelace")
    await page.get_by_role("button", name="Review order").click()
    # Confirm
    await page.get_by_role("button", name="Place order").click()
    assert "Order confirmed" in await page.inner_text("h1")


@pytest.mark.asyncio
async def test_checkout_requires_fields(page, sandbox_url):
    """Submitting shipping empty must re-render with an error (no advance)."""
    await page.goto(f"{sandbox_url}/checkout/shipping")
    await page.get_by_role("button", name="Continue to payment").click()
    assert await page.locator(".error").count() == 1
    assert "/checkout/shipping" in page.url


@pytest.mark.asyncio
async def test_login_flow(page, sandbox_url):
    await page.goto(f"{sandbox_url}/login")
    await page.fill("#username", "standard_user")
    await page.fill("#password", "secret_sauce")
    await page.get_by_role("button", name="Login").click()
    assert "Welcome, standard_user" in await page.inner_text("#welcome")


@pytest.mark.asyncio
async def test_login_rejects_bad_credentials(page, sandbox_url):
    await page.goto(f"{sandbox_url}/login")
    await page.fill("#username", "nope")
    await page.fill("#password", "wrong")
    await page.get_by_role("button", name="Login").click()
    assert await page.locator("#login-error").count() == 1
