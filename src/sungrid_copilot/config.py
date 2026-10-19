"""Application settings.

Precedence: environment variables (optionally loaded from a git-ignored `.env`) win over
`config/config.yaml`. Secrets are never stored here; provider credentials are read from the
environment by each provider in `llm/` via `require_env`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

Provider = Literal["azure_openai", "openai", "anthropic", "gemini", "fake"]
Role = Literal["default", "classifier", "extractor", "answerer"]


class ConfigError(Exception):
    """Missing or invalid configuration. Messages name the setting, never its value."""


class RoleSettings(BaseModel):
    model: str | None = None


class LLMSettings(BaseModel):
    provider: Provider = "azure_openai"
    timeout_s: float = Field(30, gt=0)
    max_retries: int = Field(2, ge=0)
    temperature: float = 0.0
    roles: dict[str, RoleSettings] = Field(default_factory=dict)

    def model_for_role(self, role: str) -> str | None:
        """Model/deployment override for a role, or None to use the provider default."""
        role_settings = self.roles.get(role)
        return role_settings.model if role_settings else None


class RetrievalSettings(BaseModel):
    top_k: int = Field(5, gt=0)
    classifier_min_conf: float = Field(0.6, ge=0, le=1)
    non_relevant_min_conf: float = Field(0.85, ge=0, le=1)
    min_score: float | None = None


class Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)


def load_env_file(path: Path = DEFAULT_ENV_PATH) -> None:
    """Load `.env` if present. Variables already set in the environment are not overridden."""
    if path.is_file():
        load_dotenv(path, override=False)


def load_settings(config_path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    """Load `.env`, then `config.yaml`, then apply environment overrides."""
    load_env_file()

    data: dict = {}
    if config_path.is_file():
        with config_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    provider = os.environ.get("LLM_PROVIDER", "").strip()
    if provider:
        data.setdefault("llm", {})["provider"] = provider

    try:
        return Settings.model_validate(data)
    except ValueError as e:
        raise ConfigError(f"Invalid settings in {config_path} or LLM_PROVIDER: {e}") from e


def require_env(name: str, provider: str) -> str:
    """Return a required environment variable, or raise ConfigError naming it and the provider."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name} for LLM provider '{provider}'. "
            "Set it in your environment or in .env (see .env.example)."
        )
    return value
