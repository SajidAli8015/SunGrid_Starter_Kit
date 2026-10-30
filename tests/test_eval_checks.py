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
        "error": None,
    }
    return base | kw


@pytest.mark.parametrize(
    "fn, expect, rec, result",
    [
        (c.category_ok, {"category_any": ["billing_account"]}, record(), True),
        (c.category_ok, {"category_any": ["incentive_rebate"]}, record(), False),
        (c.category_ok, {"category_any": []}, record(), None),
        (c.retrieval_ok, {"sources": ["03_billing", "11_trueup"]}, record(), True),
        (c.retrieval_ok, {"sources": ["03_billing", "12_autopay"]}, record(), False),
        (c.retrieval_ok, {"sources": None}, record(), None),
        (c.cited_ok, {"sources": ["03_billing", "12_autopay"]}, record(), True),
        (c.cited_ok, {"sources": ["11_trueup"]}, record(), False),
        (c.cited_ok, {"sources": []}, record(), None),
        (c.cited_ok, {"sources": ["11_trueup"]}, record(outcome="abstained", cited_stems=[]), None),
        (c.outcome_ok, {"outcome_in": ["answered", "abstained"]}, record(), True),
        (c.outcome_ok, {"outcome_in": ["ineligible"]}, record(), False),
        (c.outcome_ok, {}, record(), None),
        (c.tool_ok, {"tool_called": False}, record(), True),
        (c.tool_ok, {"tool_called": True}, record(), False),
        (c.escalation_ok, {"escalated": False}, record(), True),
        (c.escalation_ok, {"escalated": True}, record(), False),
        (c.escalation_ok, {"escalated": None}, record(), None),
    ],
)
def test_check(fn, expect, rec, result):
    assert fn(question(**expect), rec)[0] is result


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


def test_auto_pass_ignores_checks_that_are_not_specified():
    q = question(outcome_in=["answered"])
    checks, details, auto_pass = c.run_checks(q, record())
    assert checks["outcome_ok"] is True and checks["tool_ok"] is None and details == {}
    assert auto_pass is True


def test_an_allowed_abstention_passes_without_citations():
    q = question(sources=["11_trueup"], outcome_in=["answered", "abstained"], escalated=True)
    rec = record(outcome="abstained", cited_stems=[], escalated=True)
    checks, _, auto_pass = c.run_checks(q, rec)
    assert checks["cited_ok"] is None and checks["escalation_ok"] is True
    assert auto_pass is True


def test_an_answer_that_should_be_flagged_fails_auto_pass():
    q = question(outcome_in=["answered"], escalated=True)
    checks, details, auto_pass = c.run_checks(q, record(escalated=False))
    assert checks["escalation_ok"] is False and "escalation_ok" in details
    assert auto_pass is False


def test_a_missing_citation_fails_auto_pass():
    q = question(sources=["11_trueup"], outcome_in=["answered"])
    checks, details, auto_pass = c.run_checks(q, record(cited_stems=[]))
    assert checks["retrieval_ok"] is True and checks["cited_ok"] is False and "cited_ok" in details
    assert auto_pass is False


def test_auto_pass_false_on_error_or_failed_check():
    q = question(outcome_in=["answered"])
    assert c.run_checks(q, record(error="boom"))[2] is False
    assert c.run_checks(q, record(outcome="abstained"))[2] is False
