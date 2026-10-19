"""Deterministic, offline LLM client for tests and `LLM_PROVIDER=fake`. Makes no network calls."""

from __future__ import annotations

from dataclasses import dataclass

from sungrid_copilot.llm.base import LLMClient, LLMError, LLMResponse, Message

PROVIDER = "fake"
Scripted = str | LLMResponse


@dataclass(frozen=True)
class FakeCall:
    system: str
    messages: list[Message]
    temperature: float
    max_tokens: int


def describe_env() -> dict[str, str]:
    return {"Model": "fake", "API key": "not required"}


class FakeLLMClient(LLMClient):
    """Replays scripted responses and records every call it receives.

    - list: responses are returned in order.
    - dict: the first key (in insertion order) found as a substring of the system prompt or
      the last message wins.
    - `default` is returned when the script is exhausted or has no match; without a default
      that raises LLMError.
    """

    provider = PROVIDER

    def __init__(
        self,
        responses: list[Scripted] | dict[str, Scripted] | None = None,
        *,
        default: Scripted | None = None,
        model: str = "fake",
        temperature: float = 0.0,
    ):
        super().__init__(model=model, temperature=temperature)
        self._queue = list(responses) if isinstance(responses, list) else None
        self._by_key = dict(responses) if isinstance(responses, dict) else {}
        self._default = default
        self.calls: list[FakeCall] = []

    def _complete(
        self, system: str, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> LLMResponse:
        self.calls.append(FakeCall(system, [dict(m) for m in messages], temperature, max_tokens))
        scripted = self._next(system, messages[-1]["content"])
        if isinstance(scripted, LLMResponse):
            return scripted
        input_words = len(system.split()) + sum(len(m["content"].split()) for m in messages)
        return LLMResponse(
            text=scripted,
            input_tokens=input_words,
            output_tokens=len(scripted.split()),
            model=self.model,
        )

    def _next(self, system: str, last_message: str) -> Scripted:
        if self._queue:
            return self._queue.pop(0)
        for key, scripted in self._by_key.items():
            if key in system or key in last_message:
                return scripted
        if self._default is not None:
            return self._default
        raise LLMError("FakeLLMClient has no scripted response for this call.")
