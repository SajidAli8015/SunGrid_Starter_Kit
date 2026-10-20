"""Adapter + gate against the REAL stub (loaded by name from config), plus malformed fakes."""

import math
import time

import pytest

from sungrid_copilot.config import load_settings
from sungrid_copilot.eligibility.adapter import (
    EligibilityAdapter,
    InvalidInput,
    RawResult,
    ToolError,
)
from sungrid_copilot.eligibility.gate import GateDecision, Verdict, evaluate
from sungrid_copilot.eligibility.guard import format_amount

GOOD = {
    "household_zip": "94101",
    "annual_income_usd": 85000,
    "system_size_kw": 7.5,
    "installer_approved": True,
}


@pytest.fixture(scope="module")
def adapter():
    return EligibilityAdapter.from_settings(load_settings())


def _decide(adapter, **overrides):
    result = adapter.check({**GOOD, **overrides})
    assert isinstance(result, RawResult), result
    return evaluate(result.raw)


@pytest.mark.parametrize("size, amount", [(7.5, "$3,000.00"), (10, "$4,000.00"), (3, "$1,200.00")])
def test_eligible_amounts(adapter, size, amount):
    decision = _decide(adapter, system_size_kw=size)
    assert decision.verdict is Verdict.ELIGIBLE_PRELIMINARY
    assert format_amount(decision.amount) == amount


@pytest.mark.parametrize(
    "overrides, reason_word",
    [
        ({"system_size_kw": 2.9}, "size"),
        ({"system_size_kw": 10.1}, "size"),
        ({"annual_income_usd": 120000}, "income"),
        ({"household_zip": "10001"}, "ZIP"),
        ({"installer_approved": False}, "Installer"),
    ],
)
def test_ineligible_cases(adapter, overrides, reason_word):
    decision = _decide(adapter, **overrides)
    assert decision.verdict is Verdict.INELIGIBLE
    assert decision.amount is None
    assert reason_word in decision.reason


def test_income_just_below_threshold_is_eligible(adapter):
    assert _decide(adapter, annual_income_usd=119999).verdict is Verdict.ELIGIBLE_PRELIMINARY


def test_all_conditions_failing_reports_first_reason_only(adapter):
    decision = _decide(
        adapter,
        household_zip="10001",
        annual_income_usd=500000,
        system_size_kw=50,
        installer_approved=False,
    )
    assert decision.verdict is Verdict.INELIGIBLE
    assert decision.reason == "Installer is not on the SunGrid approved installer list."
    assert "ZIP" not in decision.reason and "income" not in decision.reason


@pytest.mark.parametrize("zip_value", [94101, "94101-1234", " 94101", "94101 "])
def test_zip_normalisation_accepts_variants(adapter, zip_value):
    assert _decide(adapter, household_zip=zip_value).verdict is Verdict.ELIGIBLE_PRELIMINARY


def test_int_zip_is_zero_padded():
    seen = {}
    EligibilityAdapter(lambda **kw: seen.update(kw) or {}).check({**GOOD, "household_zip": 2134})
    assert seen["household_zip"] == "02134"


@pytest.mark.parametrize(
    "field, value, problem",
    [
        ("installer_approved", "no", "not_yes_no"),  # the raw stub would treat "no" as approved
        ("installer_approved", 1, "not_yes_no"),
        ("installer_approved", None, "not_yes_no"),
        ("annual_income_usd", math.nan, "not_finite"),
        ("annual_income_usd", math.inf, "not_finite"),
        ("annual_income_usd", -5, "negative"),
        ("annual_income_usd", True, "not_a_number"),
        ("annual_income_usd", "85000", "not_a_number"),
        ("system_size_kw", 0, "not_positive"),
        ("system_size_kw", -2, "not_positive"),
        ("system_size_kw", math.nan, "not_finite"),
        ("system_size_kw", 10001, "too_large"),
        ("household_zip", "9410", "not_a_zip"),
        ("household_zip", "94101-12", "not_a_zip"),
        ("household_zip", "abcde", "not_a_zip"),
        ("household_zip", True, "not_a_zip"),
        ("household_zip", 123456, "not_a_zip"),
    ],
)
def test_invalid_inputs_never_reach_the_service(field, value, problem):
    calls = []
    adapter = EligibilityAdapter(lambda **kw: calls.append(kw))
    result = adapter.check({**GOOD, field: value})
    assert result == InvalidInput(field, problem)
    assert calls == []


def test_raw_stub_would_accept_installer_no():
    """Documents why the adapter is strict: the service trusts any non-empty string."""
    import stub_tools

    assert stub_tools.check_rebate_eligibility("94101", 85000, 7.5, "no")["eligible"] is True


def test_size_range_is_left_to_the_service(adapter):
    """The adapter does not pre-judge the program's size range."""
    assert isinstance(adapter.check({**GOOD, "system_size_kw": 50}), RawResult)


@pytest.mark.parametrize(
    "raw",
    [
        {"eligible": True, "reason": "ok"},  # missing key
        {"eligible": "yes", "reason": "ok", "estimated_rebate_usd": 100.0},
        {"eligible": 1, "reason": "ok", "estimated_rebate_usd": 100.0},
        {"eligible": False, "reason": "no", "estimated_rebate_usd": 500.0},
        {"eligible": True, "reason": "ok", "estimated_rebate_usd": 0.0},
        {"eligible": True, "reason": "ok", "estimated_rebate_usd": math.nan},
        {"eligible": True, "reason": "ok", "estimated_rebate_usd": -1.0},
        {"eligible": True, "reason": "ok", "estimated_rebate_usd": "3000"},
        {"eligible": False, "reason": "", "estimated_rebate_usd": 0.0},
        {"eligible": False, "reason": "You would normally get $500.", "estimated_rebate_usd": 0.0},
        ["not", "a", "dict"],
        None,
    ],
)
def test_malformed_results_are_tool_errors(raw):
    decision = evaluate(raw)
    assert decision.verdict is Verdict.TOOL_ERROR
    assert decision.amount is None


def test_extra_keys_are_ignored():
    raw = {"eligible": True, "reason": "ok", "estimated_rebate_usd": 10.0, "debug": "x"}
    assert evaluate(raw).verdict is Verdict.ELIGIBLE_PRELIMINARY


def test_amount_cannot_exist_on_non_eligible_decisions():
    with pytest.raises(ValueError):
        GateDecision(Verdict.INELIGIBLE, reason="no", amount=100.0)
    with pytest.raises(ValueError):
        GateDecision(Verdict.TOOL_ERROR, amount=1.0)
    with pytest.raises(ValueError):
        GateDecision(Verdict.ELIGIBLE_PRELIMINARY, reason="ok", amount=0.0)


def test_service_exception_is_tool_error_without_details():
    def boom(**kwargs):
        raise RuntimeError(f"db failed for zip {kwargs['household_zip']}")

    result = EligibilityAdapter(boom).check(GOOD)
    assert result == ToolError("exception", "RuntimeError")
    assert "94101" not in repr(result)


def test_service_timeout_is_tool_error():
    def slow(**kwargs):
        time.sleep(2)
        return {"eligible": True, "reason": "ok", "estimated_rebate_usd": 1.0}

    start = time.perf_counter()
    result = EligibilityAdapter(slow, timeout_s=0.2).check(GOOD)
    assert result == ToolError("timeout")
    assert time.perf_counter() - start < 1.5


def test_misconfigured_service_fails_loudly():
    from sungrid_copilot.config import ConfigError, Settings

    settings = Settings.model_validate({"eligibility": {"service_module": "no_such_module_xyz"}})
    with pytest.raises(ConfigError, match="service_module"):
        EligibilityAdapter.from_settings(settings)
