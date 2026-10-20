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


class EmbeddingSettings(BaseModel):
    model: str = "BAAI/bge-small-en-v1.5"


class VectorStoreSettings(BaseModel):
    path: Path = Path(".chroma")
    collection: str = "sungrid_kb"

    @property
    def resolved_path(self) -> Path:
        return _resolve(self.path)


class IngestionSettings(BaseModel):
    docs_dir: Path = Path("docs")
    manifest: Path = Path("config/doc_manifest.yaml")
    max_chunk_tokens: int = Field(350, gt=0)

    @property
    def resolved_docs_dir(self) -> Path:
        return _resolve(self.docs_dir)

    @property
    def resolved_manifest(self) -> Path:
        return _resolve(self.manifest)


class CategoriesSettings(BaseModel):
    file: Path = Path("config/categories.yaml")

    @property
    def resolved_file(self) -> Path:
        return _resolve(self.file)


class ClassifierSettings(BaseModel):
    max_tokens: int = Field(200, gt=0)
    cache_dir: Path = Path(".cache/classify")

    @property
    def resolved_cache_dir(self) -> Path:
        return _resolve(self.cache_dir)


class MessagesSettings(BaseModel):
    file: Path = Path("config/messages.yaml")

    @property
    def resolved_file(self) -> Path:
        return _resolve(self.file)


class NextStepsSettings(BaseModel):
    category: str = "incentive_rebate"  # checked against config/categories.yaml by the agent
    focus: str = (
        "Explain only the process steps that follow for the member. Do not state any dollar "
        "amounts, any eligibility result, or whether the member qualifies."
    )
    queries: dict[str, str] = Field(default_factory=dict)  # keys: ineligible, eligible


class EligibilitySettings(BaseModel):
    # The service is loaded by name so no code depends on where the stub lives.
    service_module: str = "stub_tools"
    service_function: str = "check_rebate_eligibility"
    timeout_s: float = Field(5, gt=0)
    extractor_max_tokens: int = Field(200, gt=0)
    cache_dir: Path = Path(".cache/extract")
    next_steps: NextStepsSettings = Field(default_factory=NextStepsSettings)

    @property
    def resolved_cache_dir(self) -> Path:
        return _resolve(self.cache_dir)


class AnswerSettings(BaseModel):
    max_tokens: int = Field(600, gt=0)


class AgentSettings(BaseModel):
    max_clarification_turns: int = Field(3, ge=1)
    use_llm_cache: bool = False


class LoggingSettings(BaseModel):
    path: Path = Path("logs/queries.jsonl")
    include_query_text: bool = False

    @property
    def resolved_path(self) -> Path:
        return _resolve(self.path)


class ModelPrice(BaseModel):
    input_per_1m: float | None = Field(None, ge=0)
    output_per_1m: float | None = Field(None, ge=0)


class RetrievalSettings(BaseModel):
    top_k: int = Field(5, gt=0)
    classifier_min_conf: float = Field(0.6, ge=0, le=1)
    non_relevant_min_conf: float = Field(0.85, ge=0, le=1)
    # Use the category filter only if its top-1 is within this of the unfiltered top-1.
    fallback_margin: float = Field(0.05, ge=0, le=1)
    # A confident non_relevant label is declined only if unfiltered top-1 is below this.
    non_relevant_score_ceiling: float = Field(0.60, ge=0, le=1)


class Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    categories: CategoriesSettings = Field(default_factory=CategoriesSettings)
    classifier: ClassifierSettings = Field(default_factory=ClassifierSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    vector_store: VectorStoreSettings = Field(default_factory=VectorStoreSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    messages: MessagesSettings = Field(default_factory=MessagesSettings)
    eligibility: EligibilitySettings = Field(default_factory=EligibilitySettings)
    answer: AnswerSettings = Field(default_factory=AnswerSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    # provider -> model/deployment -> price per 1M tokens
    pricing: dict[str, dict[str, ModelPrice]] = Field(default_factory=dict)


def _resolve(path: Path) -> Path:
    """Relative paths in config are relative to the repo root, not the working directory."""
    return path if path.is_absolute() else PROJECT_ROOT / path


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
