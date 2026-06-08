"""Independent success checks for benchmark tasks.

These are evaluated by the harness directly against the final page state — NOT by
trusting the agent's self-reported `finish`. That independence is what makes the
measured success rate meaningful.
"""

from __future__ import annotations


async def evaluate_check(page, check: dict) -> bool:
    """Return True if the page satisfies the success check spec."""
    kind = check.get("type")
    if kind == "url_contains":
        return check["value"].lower() in page.url.lower()
    if kind == "text_present":
        body = (await page.inner_text("body")).lower()
        return check["value"].lower() in body
    if kind == "selector_min":
        count = await page.locator(check["selector"]).count()
        return count >= int(check.get("count", 1))
    raise ValueError(f"unknown success_check type: {kind!r}")
