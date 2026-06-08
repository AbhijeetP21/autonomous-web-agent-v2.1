"""Anthropic-compatible client (default; e.g. MiniMax M3 via a custom base_url)."""

from __future__ import annotations

from web_agent.actions.schema import DECISION_SCHEMA
from web_agent.llm.base import TOOL_DESCRIPTION, TOOL_NAME, LLMClient, LLMError, loads_lenient


class AnthropicClient(LLMClient):
    def __init__(self, model, api_key, base_url="", max_tokens=1024, temperature=0.0):
        super().__init__(model, max_tokens, temperature)
        from anthropic import AsyncAnthropic

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)

    async def propose(self, system: str, user: str) -> dict:
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": TOOL_DESCRIPTION,
                        "input_schema": DECISION_SCHEMA,
                    }
                ],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Anthropic-compatible call failed: {e}") from e

        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
                return dict(block.input)
        # Fallback: some compatible endpoints return text instead of a tool_use block.
        text = "".join(getattr(b, "text", "") for b in resp.content)
        if text.strip():
            return loads_lenient(text)
        raise LLMError("no tool_use or text content returned")
