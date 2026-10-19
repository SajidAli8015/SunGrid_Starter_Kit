import pytest
from pydantic import BaseModel

from sungrid_copilot.llm import LLMError
from sungrid_copilot.llm.base import strip_code_fences
from sungrid_copilot.llm.fake import FakeLLMClient

MESSAGES = [{"role": "user", "content": "classify this"}]


class Label(BaseModel):
    category: str
    confidence: float


def test_valid_json():
    client = FakeLLMClient(['{"category": "billing_account", "confidence": 0.9}'])
    result = client.complete_json("system", MESSAGES, Label)
    assert result.value == Label(category="billing_account", confidence=0.9)
    assert len(client.calls) == 1
    assert "JSON schema" in client.calls[0].system


def test_json_inside_code_fences():
    client = FakeLLMClient(['```json\n{"category": "x", "confidence": 0.5}\n```'])
    assert client.complete_json("system", MESSAGES, Label).value.category == "x"


@pytest.mark.parametrize(
    "text", ['```\n{"a": 1}\n```', '```JSON {"a": 1} ```', '  {"a": 1}  ']
)
def test_strip_code_fences(text):
    assert strip_code_fences(text) == '{"a": 1}'


def test_invalid_then_valid_retry_feeds_back_error():
    client = FakeLLMClient(
        ["not json at all", '{"category": "x", "confidence": 0.7}'],
    )
    result = client.complete_json("system", MESSAGES, Label)
    assert result.value.confidence == 0.7
    assert len(result.responses) == 2
    retry_messages = client.calls[1].messages
    assert retry_messages[-2] == {"role": "assistant", "content": "not json at all"}
    assert "not valid JSON" in retry_messages[-1]["content"]
    assert result.input_tokens == sum(r.input_tokens for r in result.responses)


def test_final_failure_raises_llm_error():
    client = FakeLLMClient(['{"category": "x"}', '{"confidence": "high"}'])
    with pytest.raises(LLMError, match="Label"):
        client.complete_json("system", MESSAGES, Label, retries=1)
    assert len(client.calls) == 2


def test_provider_exception_is_wrapped_and_redacted():
    class Boom(FakeLLMClient):
        def _complete(self, *args, **kwargs):
            raise RuntimeError("auth failed for key sk-abc123")

    client = Boom()
    client._secrets = ("sk-abc123",)
    with pytest.raises(LLMError) as excinfo:
        client.complete("system", MESSAGES)
    assert "sk-abc123" not in str(excinfo.value)
    assert "RuntimeError" in str(excinfo.value)
