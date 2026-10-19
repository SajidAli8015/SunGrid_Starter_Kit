"""Anthropic Messages API client. Not tested end to end (see NOTES.md)."""

from __future__ import annotations

import os

from pydantic import BaseModel, SecretStr

from sungrid_copilot.config import LLMSettings, require_env
from sungrid_copilot.llm.base import LLMClient, LLMError, LLMResponse, Message

PROVIDER = "anthropic"


class AnthropicSettings(BaseModel):
    api_key: SecretStr
    model: str

    @classmethod
    def from_env(cls) -> AnthropicSettings:
        return cls(
            api_key=SecretStr(require_env("ANTHROPIC_API_KEY", PROVIDER)),
            model=require_env("ANTHROPIC_MODEL", PROVIDER),
        )


def describe_env() -> dict[str, str]:
    return {
        "Model": os.environ.get("ANTHROPIC_MODEL", "").strip() or "(not set)",
        "API key": "set" if os.environ.get("ANTHROPIC_API_KEY", "").strip() else "MISSING",
    }


class AnthropicClient(LLMClient):
    provider = PROVIDER

    def __init__(self, llm: LLMSettings, *, model_override: str | None = None):
        settings = AnthropicSettings.from_env()
        api_key = settings.api_key.get_secret_value()
        super().__init__(
            model=model_override or settings.model, temperature=llm.temperature, secrets=(api_key,)
        )
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("The 'anthropic' package is required for anthropic.") from e
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=llm.timeout_s, max_retries=llm.max_retries
        )

    def _complete(
        self, system: str, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> LLMResponse:
        # The system prompt is a separate parameter and max_tokens is required. The installed
        # SDK (anthropic 1.x) has no `temperature` parameter, so it is not sent (see NOTES.md).
        response = self._client.messages.create(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model or self.model,
        )
