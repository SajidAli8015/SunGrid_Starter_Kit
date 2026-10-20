import pytest

from sungrid_copilot.evaluation import checks as c
from sungrid_copilot.evaluation.schema import Question


def question(**expect):
    turns = expect.pop("turns", [{"say": "q"}])
    return Question(id="x", turns=turns, expect=expect)


def record(**kw):
    base = {
        "category": "billing_account",
        "retrieved_stems": ["03_billing", "11_trueup"],
        "cited_stems": ["03_billing"],
        "outcome": "answered",
        "turns": [{"outcome": "answered", "text": "Due in 21 days."}],
        "service_called": False,
        "escalated": False,
        "final_text": "Due in 21 days.",
        "error": None,
    }
    return base | kw


@pytest.mark.parametrize(
    "fn, expect, rec, result",
    [
        (c.category_ok, {"category_any": ["billing_account"]}, record(), True),
        (c.category_ok, {"category_any": ["incentive_rebate"]}, record(), False),
        (c.category_ok, {"category_any": []}, record(), None),
        (c.retrieval_all, {"sources": ["03_billing", "11_trueup"]}, record(), True),
        (c.retrieval_all, {"sources": ["03_billing", "12_autopay"]}, record(), False),
        (c.retrieval_any, {"sources": ["12_autopay", "11_trueup"]}, record(), True),
        (c.retrieval_any, {"sources": ["12_autopay"]}, record(), False),
        (c.retrieval_all, {"sources": None}, record(), None),
        (c.cited_any, {"sources": ["03_billing"]}, record(), True),
        (c.cited_any, {"sources": ["11_trueup"]}, record(), False),
        (c.outcome_ok, {"outcome_in": ["answered", "abstained"]}, record(), True),
        (c.outcome_ok, {"outcome_in": ["ineligible"]}, record(), False),
        (c.outcome_ok, {}, record(), None),
        (c.tool_ok, {"tool_called": False}, record(), True),
        (c.tool_ok, {"tool_called": True}, record(), False),
        (c.escalation_ok, {"escalated": False}, record(), True),
        (c.escalation_ok, {"escalated": True}, record(), False),
        (c.escalation_ok, {"escalated": None}, record(), None),
        (c.contains_ok, {"must_contain": ["21\\s*DAYS", "due"]}, record(), True),
        (c.contains_ok, {"must_contain": ["21", "45"]}, record(), False),
        (c.not_contains_ok, {"must_not_contain": ["\\$"]}, record(), True),
        (c.not_contains_ok, {"must_not_contain": ["due.in"]}, record(), False),
    ],
)
def test_check(fn, expect, rec, result):
    assert fn(question(**expect), rec)[0] is result


def test_regexes_are_case_insensitive_and_dotall():
    rec = record(final_text="Line one\nLINE two")
    assert c.contains_ok(question(must_contain=["one.line two"]), rec)[0] is True


def test_turn_expect_outcome_is_checked():
    q = question(turns=[{"say": "a", "expect_outcome": "needs_info"}, {"say": "b"}])
    good = record(turns=[{"outcome": "needs_info", "text": ""}, {"outcome": "answered", "text": ""}])
    bad = record(turns=[{"outcome": "answered", "text": ""}, {"outcome": "answered", "text": ""}])
    assert c.outcome_ok(q, good)[0] is True
    result, detail = c.outcome_ok(q, bad)
    assert result is False and "turn 1" in detail


def test_hard_gate_flags_dollar_in_ineligible_reply():
    rec = record(turns=[{"outcome": "ineligible", "text": "You do not qualify. Most get $500."}])
    assert c.hard_gate_ok(question(), rec)[0] is False
    ok = record(turns=[{"outcome": "eligible_preliminary", "text": "Estimated $3,000.00."}])
    assert c.hard_gate_ok(question(), ok)[0] is True


def test_hard_gate_checks_every_turn():
    rec = record(turns=[{"outcome": "needs_info", "text": "Up to $4,000"},
                        {"outcome": "eligible_preliminary", "text": "$1.00"}])
    assert c.hard_gate_ok(question(), rec)[0] is False


def test_auto_pass_ignores_informational_and_none_checks():
    q = question(sources=["11_trueup"], outcome_in=["answered"])
    checks, details, auto_pass = c.run_checks(q, record(cited_stems=[]))
    assert checks["cited_any"] is False and "cited_any" in details
    assert checks["tool_ok"] is None
    assert auto_pass is True


def test_auto_pass_false_on_error_or_failed_check():
    q = question(outcome_in=["answered"])
    assert c.run_checks(q, record(error="boom"))[2] is False
    assert c.run_checks(q, record(outcome="abstained"))[2] is False
