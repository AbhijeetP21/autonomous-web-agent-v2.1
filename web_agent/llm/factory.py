"""Select and build the configured LLM client."""

from __future__ import annotations

from web_agent.config import Settings, get_settings
from web_agent.llm.base import LLMClient


def build_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    if not settings.llm_api_key:
        raise RuntimeError(
            "LLM_API_KEY is not set. Copy .env.example to .env and add your key "
            "(MiniMax M3 = anthropic provider; OpenRouter/DeepSeek = openai provider)."
        )
    common = dict(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )
    if settings.llm_provider == "anthropic":
        from web_agent.llm.anthropic_client import AnthropicClient

        return AnthropicClient(**common)
    if settings.llm_provider == "openai":
        from web_agent.llm.openai_client import OpenAIClient

        return OpenAIClient(**common)
    raise RuntimeError(f"unsupported provider: {settings.llm_provider}")
