"""Provider-agnostic LLM client interface.

A client takes a system prompt and a single composed user prompt and returns the
raw ``{reasoning, action}`` object (validated downstream by the planner). Keeping
the interface this thin means swapping providers — Anthropic-compatible (MiniMax
today), OpenAI-compatible (OpenRouter/DeepSeek now, SynapticaAI later) — is a
config change, not a code change.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

TOOL_NAME = "take_action"
TOOL_DESCRIPTION = (
    "Record your reasoning and the single next action to take in the browser. "
    "You must always call this tool."
)


class LLMError(RuntimeError):
    """Raised when the provider call fails or returns no usable structured output."""


class LLMClient(ABC):
    def __init__(self, model: str, max_tokens: int = 1024, temperature: float = 0.0):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @abstractmethod
    async def propose(self, system: str, user: str) -> dict:
        """Return the raw decision object ({"reasoning": ..., "action": {...}})."""

    @property
    def label(self) -> str:
        return f"{type(self).__name__}({self.model})"


def loads_lenient(text: str) -> dict:
    """Best-effort JSON parse: tolerate markdown fences / surrounding prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first balanced-looking object in the string.
        start, depth = text.find("{"), 0
        if start != -1:
            for i in range(start, len(text)):
                depth += text[i] == "{"
                depth -= text[i] == "}"
                if depth == 0:
                    return json.loads(text[start : i + 1])
        raise LLMError(f"could not parse JSON from model output: {text[:200]!r}") from None
