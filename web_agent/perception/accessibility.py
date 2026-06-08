"""Perception layer.

Rather than feeding the model raw HTML (token-heavy and noisy), we extract a
**reduced, indexed view** of the page: only the interactive/role-bearing elements,
each tagged in the live DOM with a stable ``data-agent-id`` so the executor can
resolve the model's chosen ``element_id`` back to a Playwright locator.

The model sees a compact listing like::

    [1] button "Add"
    [2] textbox "New todo" (placeholder: What needs doing?)
    [3] link "Checkout"

This is the core token-efficiency decision of the project.
"""

from __future__ import annotations

from pydantic import BaseModel

# JS run on the page each perception step. It (re)tags interactive elements with a
# fresh sequential data-agent-id and returns a structured snapshot. Re-running every
# step keeps ids consistent with the *current* DOM (which mutates as the agent acts).
_PERCEIVE_JS = r"""
() => {
  const SELECTOR = [
    'a[href]', 'button', 'input', 'textarea', 'select',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=tab]',
    '[role=menuitem]', '[onclick]', 'summary', '[contenteditable=true]'
  ].join(',');

  // Clear stale tags so ids never leak across steps.
  document.querySelectorAll('[data-agent-id]').forEach(e => e.removeAttribute('data-agent-id'));

  const isVisible = (el) => {
    if (el.getClientRects().length === 0) return false;
    const s = window.getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity || '1') > 0;
  };

  const accessibleName = (el) => {
    let n = el.getAttribute('aria-label') || '';
    if (!n && el.labels && el.labels.length) n = el.labels[0].innerText || '';
    if (!n) n = (el.innerText || el.textContent || '').trim();
    if (!n) n = el.getAttribute('placeholder') || '';
    if (!n) n = el.getAttribute('value') || '';
    if (!n) n = el.getAttribute('name') || '';
    return n.replace(/\s+/g, ' ').trim().slice(0, 120);
  };

  const elements = [];
  let id = 1;
  for (const el of document.querySelectorAll(SELECTOR)) {
    if (!isVisible(el)) continue;
    el.setAttribute('data-agent-id', String(id));
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const editable =
      (tag === 'input' && !['button', 'submit', 'checkbox', 'radio', 'hidden'].includes(type)) ||
      tag === 'textarea' || el.getAttribute('contenteditable') === 'true';
    elements.push({
      id, tag, type,
      role: el.getAttribute('role') || '',
      name: accessibleName(el),
      value: (el.value !== undefined ? String(el.value) : '').slice(0, 80),
      placeholder: el.getAttribute('placeholder') || '',
      editable,
      disabled: !!el.disabled,
    });
    id++;
  }

  const grab = (sel) => Array.from(document.querySelectorAll(sel))
    .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean);

  return {
    url: location.href,
    title: document.title,
    headings: grab('h1, h2').slice(0, 8),
    messages: grab('.error, .ok, [role=alert], #order-status, #welcome').slice(0, 8),
    elements,
  };
}
"""


class Element(BaseModel):
    id: int
    tag: str
    type: str = ""
    role: str = ""
    name: str = ""
    value: str = ""
    placeholder: str = ""
    editable: bool = False
    disabled: bool = False

    def display_role(self) -> str:
        if self.role:
            return self.role
        if self.tag == "a":
            return "link"
        if self.tag == "select":
            return "combobox"
        if self.tag == "textarea":
            return "textbox"
        if self.tag == "input":
            return {
                "text": "textbox", "email": "textbox", "search": "textbox",
                "password": "textbox", "tel": "textbox", "url": "textbox", "number": "textbox",
                "checkbox": "checkbox", "radio": "radio", "submit": "button", "button": "button",
            }.get(self.type, "textbox")
        return self.tag

    def render(self) -> str:
        name = self.name.replace('"', "'")  # keep the quoted listing unambiguous
        parts = [f'[{self.id}] {self.display_role()} "{name}"']
        if self.editable and self.value:
            parts.append(f"(current value: {self.value})")
        elif self.placeholder and self.placeholder != self.name:
            parts.append(f"(placeholder: {self.placeholder})")
        if self.disabled:
            parts.append("(disabled)")
        return " ".join(parts)


class Observation(BaseModel):
    url: str
    title: str
    headings: list[str] = []
    messages: list[str] = []
    elements: list[Element] = []
    truncated: bool = False

    def element_ids(self) -> set[int]:
        return {e.id for e in self.elements}

    def element(self, element_id: int) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)

    def to_prompt(self) -> str:
        lines = [f"URL: {self.url}", f"Title: {self.title}"]
        if self.headings:
            lines.append("Headings: " + " | ".join(self.headings))
        if self.messages:
            lines.append("Page messages: " + " | ".join(self.messages))
        lines.append("")
        lines.append("Interactive elements:")
        if self.elements:
            lines.extend("  " + e.render() for e in self.elements)
        else:
            lines.append("  (none detected)")
        if self.truncated:
            lines.append("  ... (element list truncated)")
        return "\n".join(lines)


async def perceive(page, max_elements: int = 80) -> Observation:
    """Extract a reduced, indexed observation of the current page state."""
    raw = await page.evaluate(_PERCEIVE_JS)
    elements = [Element(**e) for e in raw["elements"]]
    truncated = len(elements) > max_elements
    return Observation(
        url=raw["url"],
        title=raw["title"],
        headings=raw.get("headings", []),
        messages=raw.get("messages", []),
        elements=elements[:max_elements],
        truncated=truncated,
    )
