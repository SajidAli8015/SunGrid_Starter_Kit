"""Per-request LLM usage: every call's role, model, tokens and latency, plus estimated cost.

`TrackedLLM` wraps any `LLMClient` (provider-independent). One `UsageTracker` is shared by the
agent's clients and reset at the start of each request. Not thread-safe: one request at a time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sungrid_copilot.config import ModelPrice
from sungrid_copilot.llm import LLMClient, LLMError, LLMResponse
from sungrid_copilot.llm.base import Message


@dataclass(frozen=True)
class CallRecord:
    role: str
    model: str  # the configured model/deployment (the pricing key)
    input_tokens: int
    output_tokens: int
    latency_s: float
    error: str | None = None  # exception type name if the call failed


@dataclass
class UsageTracker:
    calls: list[CallRecord] = field(default_factory=list)

    def reset(self) -> None:
        self.calls = []

    def record(self, call: CallRecord) -> None:
        self.calls.append(call)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    def by_call(self) -> list[dict]:
        return [asdict(c) | {"latency_s": round(c.latency_s, 3)} for c in self.calls]


def estimate_cost(
    calls: list[CallRecord], provider: str, pricing: dict[str, dict[str, ModelPrice]]
) -> float | None:
    """USD, or None if any call's model has no complete price."""
    total = 0.0
    for c in calls:
        price = pricing.get(provider, {}).get(c.model)
        if price is None or price.input_per_1m is None or price.output_per_1m is None:
            return None
        total += c.input_tokens * price.input_per_1m / 1e6 + c.output_tokens * price.output_per_1m / 1e6
    return round(total, 6)


class TrackedLLM(LLMClient):
    """Delegates to `inner` and records each completion (complete_json retries included)."""

    def __init__(self, inner: LLMClient, role: str, tracker: UsageTracker):
        super().__init__(model=inner.model, temperature=inner.default_temperature)
        self.inner = inner
        self.role = role
        self.tracker = tracker
        self.provider = inner.provider

    def _complete(self, *args, **kwargs) -> LLMResponse:  # pragma: no cover - complete() delegates
        raise NotImplementedError

    def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        try:
            response = self.inner.complete(
                system, messages, temperature=temperature, max_tokens=max_tokens
            )
        except LLMError as e:
            self.tracker.record(CallRecord(self.role, self.model, 0, 0, 0.0, type(e).__name__))
            raise
        self.tracker.record(
            CallRecord(
                self.role,
                self.model,
                response.input_tokens,
                response.output_tokens,
                response.latency_s,
            )
        )
        return response
