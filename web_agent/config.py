"""Environment-driven configuration (loaded from .env or the process environment)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM ---
    llm_provider: str = Field(default="anthropic")  # "anthropic" | "openai"
    llm_base_url: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="MiniMax-M3")
    llm_max_tokens: int = Field(default=1024)
    llm_temperature: float = Field(default=0.0)

    # --- Agent caps / guardrails ---
    agent_max_steps: int = Field(default=25)
    agent_retry_max: int = Field(default=3)
    agent_loop_window: int = Field(default=3)
    agent_domain_allowlist: str = Field(default="localhost,127.0.0.1,www.saucedemo.com")
    agent_confirm_sensitive: bool = Field(default=False)
    agent_headless: bool = Field(default=True)

    # --- Storage ---
    db_path: Path = Field(default=Path("./data/agent.db"))
    screenshot_dir: Path = Field(default=Path("./data/screenshots"))

    # --- Sandbox ---
    sandbox_port: int = Field(default=8000)

    @field_validator("llm_provider")
    @classmethod
    def _provider_supported(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"anthropic", "openai"}:
            raise ValueError(f"LLM_PROVIDER must be 'anthropic' or 'openai', got {v!r}")
        return v

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.agent_domain_allowlist.split(",") if d.strip()]

    def ensure_dirs(self) -> None:
        """Create runtime directories if missing."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Cached settings accessor."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
