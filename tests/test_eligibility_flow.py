"""Flow, renderer, guard, messages wording and privacy. No LLM."""

import logging
import re

import pytest
import yaml

from sungrid_copilot.config import load_settings
from sungrid_copilot.eligibility.adapter import EligibilityAdapter, InvalidInput, ToolError
from sungrid_copilot.eligibility.flow import Decision, NeedsInfo, TierNotHousehold, run_eligibility
from sungrid_copilot.eligibility.gate import GateDecision, Verdict
from sungrid_copilot.eligibility.guard import check_final_text, find_numbers
from sungrid_copilot.eligibility.render import load_messages, render
from sungrid_copilot.eligibility.slots import EligibilitySlots

MESSAGES = load_messages()
FULL = EligibilitySlots(
    household_zip="94101",
    annual_income_usd=85000,
    system_size_kw=7.5,
    installer_approved=True,
    member_tier="household",
)


class Spy:
    """A fake service that records calls and returns a scripted result."""

    def __init__(self, result=None):
        self.result = result or {"eligible": True, "reason": "ok", "estimated_rebate_usd": 3000.0}
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _run(slots, result=None):
    spy = Spy(result)
    return run_eligibility(slots, EligibilityAdapter(spy)), spy


def test_missing_slots_ask_one_combined_question_without_calling_service():
    outcome, spy = _run(EligibilitySlots(system_size_kw=6))
    assert outcome == NeedsInfo(
        ("household_zip", "annual_income_usd", "installer_approved", "member_tier")
    )
    assert spy.calls == []
    text = render(outcome, MESSAGES)
    assert text.startswith(MESSAGES.text("ask_missing_intro"))
    assert text.count("\n- ") == 4
    assert "adjusted gross income" in text
    assert "size" not in text.lower().split("\n- ")[0]  # size was given, not asked
    assert not outcome.escalate


@pytest.mark.parametrize("tier", ["community", "commercial"])
def test_non_household_tier_does_not_call_service(tier):
    outcome, spy = _run(FULL.model_copy(update={"member_tier": tier}))
    assert outcome == TierNotHousehold(tier)
    assert outcome.escalate
    assert spy.calls == []
    text = render(outcome, MESSAGES)
    assert "Household-tier" in text and "flagged" in text and "$" not in text


def test_known_non_household_tier_short_circuits_missing_slots():
    outcome, spy = _run(EligibilitySlots(member_tier="community"))
    assert isinstance(outcome, TierNotHousehold)
    assert spy.calls == []


def test_complete_household_slots_call_service_exactly_once():
    outcome, spy = _run(FULL)
    assert len(spy.calls) == 1
    assert isinstance(outcome, Decision)
    assert outcome.decision.verdict is Verdict.ELIGIBLE_PRELIMINARY


def test_malformed_service_result_becomes_escalated_tool_error():
    outcome, _ = _run(FULL, {"eligible": False, "reason": "no", "estimated_rebate_usd": 500.0})
    assert isinstance(outcome, ToolError) and outcome.kind == "malformed_result"
    assert outcome.escalate
    text = render(outcome, MESSAGES)
    assert "$" not in text and "500" not in text


def test_invalid_input_is_rendered_from_messages():
    outcome = run_eligibility(
        FULL.model_copy(update={"annual_income_usd": float("nan")}), EligibilityAdapter(Spy())
    )
    assert outcome == InvalidInput("annual_income_usd", "not_finite")
    text = render(outcome, MESSAGES)
    assert "annual household income" in text and "nan" not in text.lower()


def test_ineligible_render_has_no_amount_and_quotes_reason():
    outcome = Decision(GateDecision(Verdict.INELIGIBLE, reason="Household income exceeds the threshold."))
    text = render(outcome, MESSAGES)
    assert "$" not in text
    assert '"Household income exceeds the threshold."' in text
    assert "first condition" in text
    assert check_final_text(text, outcome, MESSAGES) == []


def test_eligible_render_contains_exact_amount_and_caveat():
    outcome = Decision(GateDecision(Verdict.ELIGIBLE_PRELIMINARY, reason="ok", amount=3000.0))
    text = render(outcome, MESSAGES)
    assert "$3,000.00" in text
    assert MESSAGES.text("eligible_caveat") in text
    assert check_final_text(text, outcome, MESSAGES) == []


def test_guard_flags_amount_in_ineligible_reply():
    outcome = Decision(GateDecision(Verdict.INELIGIBLE, reason="Installer not approved."))
    text = render(outcome, MESSAGES) + " Most members get $500 back."
    assert check_final_text(text, outcome, MESSAGES) == ["amount in a non-eligible reply: $500"]
    for sneaky in ["about 500 dollars", "USD 500", "a $ refund"]:
        assert check_final_text(f"{render(outcome, MESSAGES)} {sneaky}", outcome, MESSAGES)


@pytest.mark.parametrize(
    "outcome",
    [NeedsInfo(("household_zip",)), TierNotHousehold("community"), ToolError("timeout"),
     InvalidInput("household_zip", "not_a_zip")],
)
def test_guard_flags_any_amount_for_non_decisions(outcome):
    assert check_final_text(render(outcome, MESSAGES) + " Up to $4,000.", outcome, MESSAGES)


INELIGIBLE = Decision(GateDecision(Verdict.INELIGIBLE, reason="Household income exceeds the regional threshold."))


@pytest.mark.parametrize(
    "llm_text",
    [
        "Households normally get up to 4,000 for a system like this.",
        "The cap is 4000 per household.",
        "The rebate is 40 cents per watt.",
        "It pays 0.40 per watt.",
        "You would have received about 3k.",
    ],
)
def test_guard_flags_numbers_in_the_llm_part_of_a_non_eligible_reply(llm_text):
    text = f"{render(INELIGIBLE, MESSAGES)}\n\n{llm_text}"
    assert check_final_text(text, INELIGIBLE, MESSAGES, llm_text=llm_text)


def test_guard_allows_ordinary_numbers_in_the_llm_part():
    llm_text = "You can appeal within 30 days; incomplete applications are held for 15 business days."
    text = f"{render(INELIGIBLE, MESSAGES)}\n\n{llm_text}"
    assert check_final_text(text, INELIGIBLE, MESSAGES, llm_text=llm_text) == []


def test_deterministic_ineligible_text_never_trips_the_guard():
    """Every reason the real service can give, rendered, passes (with and without an LLM part)."""
    import stub_tools

    base = dict(household_zip="94101", annual_income_usd=85000.0, system_size_kw=7.5,
                installer_approved=True)
    failing = [{"installer_approved": False}, {"household_zip": "10001"},
               {"annual_income_usd": 150000.0}, {"system_size_kw": 12.0}]
    for change in failing:
        raw = stub_tools.check_rebate_eligibility(**{**base, **change})
        outcome = Decision(GateDecision(Verdict.INELIGIBLE, reason=raw["reason"]))
        text = render(outcome, MESSAGES)
        assert check_final_text(text, outcome, MESSAGES) == [], raw["reason"]
        assert find_numbers(text) == [], raw["reason"]  # even "3kW-10kW" is not a match
        clean = "You can appeal within 30 days."
        assert check_final_text(f"{text}\n\n{clean}", outcome, MESSAGES, llm_text=clean) == []


def test_guard_flags_wrong_amount_and_missing_caveat_in_eligible_reply():
    outcome = Decision(GateDecision(Verdict.ELIGIBLE_PRELIMINARY, reason="ok", amount=3000.0))
    base = render(outcome, MESSAGES)
    assert check_final_text(base + " The cap is $4,000.00.", outcome, MESSAGES) == [
        "amount other than the service's $3,000.00: $4,000.00"
    ]
    no_caveat = base.split("\n\n")[0]
    assert "the preliminary-check caveat is missing" in check_final_text(no_caveat, outcome, MESSAGES)
    assert check_final_text("You get $3,000, great.", outcome, MESSAGES)  # wrong format


def test_messages_wording_rules():
    with load_settings().messages.resolved_file.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    ineligible = raw["ineligible"].lower()
    assert "$" not in ineligible
    for word in ["estimate", "would", "normally", "up to"]:
        assert word not in ineligible, word
    assert "{reason}" in raw["ineligible"]
    assert re.findall(r"\d", raw["eligible_caveat"]) == []
    assert re.findall(r"\d", raw["eligible_preliminary"].replace("{amount}", "")) == []
    for key in ["tier_not_household", "tool_error", "ask_missing_intro", "invalid_input"]:
        assert "$" not in raw[key]


def test_no_member_values_are_logged(caplog):
    secret_income, secret_zip = 87654.0, "94103"
    slots = FULL.model_copy(update={"annual_income_usd": secret_income, "household_zip": secret_zip})
    with caplog.at_level(logging.DEBUG):
        for service in [Spy(), Spy({"eligible": "?"}), _raising]:
            outcome = run_eligibility(slots, EligibilityAdapter(service))
            render(outcome, MESSAGES)
        run_eligibility(slots.model_copy(update={"system_size_kw": -1}), EligibilityAdapter(Spy()))
    assert "87654" not in caplog.text and secret_zip not in caplog.text


def _raising(**kwargs):
    raise ValueError(f"bad input {kwargs}")
