"""OpenAI-compatible client (e.g. OpenRouter, DeepSeek, or any OpenAI-shaped endpoint)."""

from __future__ import annotations

import json

from web_agent.actions.schema import DECISION_SCHEMA
from web_agent.llm.base import TOOL_DESCRIPTION, TOOL_NAME, LLMClient, LLMError, loads_lenient


class OpenAIClient(LLMClient):
    def __init__(self, model, api_key, base_url="", max_tokens=1024, temperature=0.0):
        super().__init__(model, max_tokens, temperature)
        from openai import AsyncOpenAI

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def propose(self, system: str, user: str) -> dict:
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": TOOL_NAME,
                            "description": TOOL_DESCRIPTION,
                            "parameters": DECISION_SCHEMA,
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            )
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"OpenAI-compatible call failed: {e}") from e

        msg = resp.choices[0].message
        if msg.tool_calls:
            args = msg.tool_calls[0].function.arguments
            try:
                return json.loads(args)
            except json.JSONDecodeError as e:
                raise LLMError(f"tool arguments were not valid JSON: {args[:200]!r}") from e
        if msg.content:
            return loads_lenient(msg.content)
        raise LLMError("no tool_calls or content returned")
