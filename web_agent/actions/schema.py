"""Action whitelist (guardrail).

The planner may only emit one of a fixed set of actions, expressed as a single
``Action`` model with a ``type`` enum and per-type required fields enforced by a
validator. Anything outside this set — or missing required fields — fails to parse
and is rejected before it ever reaches the browser. Using one flat model (rather
than a nested discriminated union) keeps the JSON schema simple and robust across
different LLM providers' tool-calling implementations.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, model_validator


class ActionType(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    WAIT = "wait"
    FINISH = "finish"
    ASK_USER = "ask_user"


# Fields that must be present for each action type.
_REQUIRED: dict[ActionType, tuple[str, ...]] = {
    ActionType.NAVIGATE: ("url",),
    ActionType.CLICK: ("element_id",),
    ActionType.TYPE: ("element_id", "text"),
    ActionType.SELECT: ("element_id", "value"),
    ActionType.SCROLL: ("direction",),
    ActionType.WAIT: ("ms",),
    ActionType.FINISH: ("success", "summary"),
    ActionType.ASK_USER: ("question",),
}

# Actions that change external/page state in a way worth gating on (confirmation mode).
SENSITIVE = {ActionType.NAVIGATE}


class Action(BaseModel):
    type: ActionType
    element_id: int | None = None
    url: str | None = None
    text: str | None = None
    value: str | None = None
    direction: Literal["up", "down"] | None = None
    ms: int | None = None
    success: bool | None = None
    summary: str | None = None
    question: str | None = None
    submit: bool = False  # for TYPE: press Enter after typing

    @model_validator(mode="after")
    def _require_fields(self) -> Action:
        missing = [f for f in _REQUIRED[self.type] if getattr(self, f) is None]
        if missing:
            raise ValueError(
                f"action '{self.type.value}' is missing required field(s): {', '.join(missing)}"
            )
        if self.type is ActionType.WAIT and self.ms is not None and self.ms > 10_000:
            self.ms = 10_000  # clamp absurd waits
        return self

    def describe(self) -> str:
        t = self.type
        if t is ActionType.NAVIGATE:
            return f"navigate to {self.url}"
        if t is ActionType.CLICK:
            return f"click element [{self.element_id}]"
        if t is ActionType.TYPE:
            return f"type {self.text!r} into element [{self.element_id}]" + (
                " then submit" if self.submit else ""
            )
        if t is ActionType.SELECT:
            return f"select {self.value!r} in element [{self.element_id}]"
        if t is ActionType.SCROLL:
            return f"scroll {self.direction}"
        if t is ActionType.WAIT:
            return f"wait {self.ms}ms"
        if t is ActionType.FINISH:
            return f"finish (success={self.success}): {self.summary}"
        return f"ask user: {self.question}"


class Decision(BaseModel):
    """What the planner asks the LLM for each step: reasoning + a single action."""

    reasoning: str = ""
    action: Action


def parse_action(data: dict) -> Action:
    """Validate raw model output into an Action (raises ValueError if invalid)."""
    return Action.model_validate(data)


def parse_decision(data: dict) -> Decision:
    """Validate raw model output into a Decision (raises ValueError if invalid)."""
    return Decision.model_validate(data)


# JSON schema describing the {reasoning, action} object the planner asks the LLM for.
# Shared by both the Anthropic (tool input_schema) and OpenAI (json_schema) clients.
DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "One or two sentences: why this action moves toward the goal.",
        },
        "action": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [t.value for t in ActionType],
                    "description": "The action to take.",
                },
                "element_id": {
                    "type": "integer",
                    "description": "Target element id from the observation (click/type/select).",
                },
                "url": {"type": "string", "description": "Absolute URL (navigate only)."},
                "text": {"type": "string", "description": "Text to type (type only)."},
                "value": {"type": "string", "description": "Option value (select only)."},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "ms": {"type": "integer", "description": "Milliseconds to wait (wait only)."},
                "submit": {
                    "type": "boolean",
                    "description": "If true with type, press Enter after typing.",
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether the goal was achieved (finish only).",
                },
                "summary": {"type": "string", "description": "Result summary (finish only)."},
                "question": {"type": "string", "description": "Question for the user (ask_user)."},
            },
            "required": ["type"],
        },
    },
    "required": ["reasoning", "action"],
}
