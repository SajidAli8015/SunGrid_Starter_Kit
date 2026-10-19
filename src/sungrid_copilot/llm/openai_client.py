"""OpenAI chat client. Not tested end to end (see NOTES.md)."""

from __future__ import annotations

import os

from pydantic import BaseModel, SecretStr

from sungrid_copilot.config import LLMSettings, require_env
from sungrid_copilot.llm.base import LLMClient, LLMError, LLMResponse, Message

PROVIDER = "openai"


class OpenAISettings(BaseModel):
    api_key: SecretStr
    model: str

    @classmethod
    def from_env(cls) -> OpenAISettings:
        return cls(
            api_key=SecretStr(require_env("OPENAI_API_KEY", PROVIDER)),
            model=require_env("OPENAI_MODEL", PROVIDER),
        )


def describe_env() -> dict[str, str]:
    return {
        "Model": os.environ.get("OPENAI_MODEL", "").strip() or "(not set)",
        "API key": "set" if os.environ.get("OPENAI_API_KEY", "").strip() else "MISSING",
    }


class OpenAIClient(LLMClient):
    provider = PROVIDER

    def __init__(self, llm: LLMSettings, *, model_override: str | None = None):
        settings = OpenAISettings.from_env()
        api_key = settings.api_key.get_secret_value()
        super().__init__(
            model=model_override or settings.model, temperature=llm.temperature, secrets=(api_key,)
        )
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("The 'openai' package is required for openai.") from e
        self._client = OpenAI(api_key=api_key, timeout=llm.timeout_s, max_retries=llm.max_retries)

    def _complete(
        self, system: str, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model or self.model,
        )
