"""Cost estimation: which price applies to a call (F9 in the review of 6619e93)."""

from sungrid_copilot.config import ModelPrice
from sungrid_copilot.usage import CallRecord, estimate_cost

PRICING = {
    "azure_openai": {
        "gpt-4o": ModelPrice(input_per_1m=2.50, output_per_1m=10.00),
        "gpt-4o-mini": ModelPrice(input_per_1m=0.15, output_per_1m=0.60),
    }
}


def call(model, api_model=None, tokens_in=1_000_000, tokens_out=0):
    return CallRecord("answerer", model, tokens_in, tokens_out, 0.1, api_model=api_model)


def test_configured_name_that_is_a_pricing_key_is_priced():
    assert estimate_cost([call("gpt-4o")], "azure_openai", PRICING) == 2.50


def test_deployment_with_another_name_is_priced_by_the_model_it_reports():
    calls = [call("sungrid-prod-chat", api_model="gpt-4o-2024-11-20")]
    assert estimate_cost(calls, "azure_openai", PRICING) == 2.50


def test_a_dated_model_never_takes_a_shorter_models_price():
    calls = [call("sungrid-prod-chat", api_model="gpt-4o-mini-2024-07-18")]
    assert estimate_cost(calls, "azure_openai", PRICING) == 0.15


def test_optional_deployment_map_wins():
    model_map = {"azure_openai": {"sungrid-prod-chat": "gpt-4o-mini"}}
    calls = [call("sungrid-prod-chat", api_model="something-unexpected")]
    assert estimate_cost(calls, "azure_openai", PRICING, model_map) == 0.15


def test_unknown_model_has_no_cost():
    calls = [call("sungrid-prod-chat", api_model="o1-2024-12-17")]
    assert estimate_cost(calls, "azure_openai", PRICING) is None
