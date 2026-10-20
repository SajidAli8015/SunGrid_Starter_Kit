"""Automated checks on one question's record. Each returns (result, detail).

result is None when the check is not specified for the question, else True/False. The detail is a
short explanation used in the failing-question list.
"""

from __future__ import annotations

import re

from sungrid_copilot.evaluation.schema import Question

CheckResult = tuple[bool | None, str]

# Outcomes whose reply must never contain a "$" (applied to every question, every turn).
NO_DOLLAR_OUTCOMES = {"ineligible", "tier_not_household", "needs_info", "invalid_input", "tool_error"}
CHECK_NAMES = [
    "category_ok",
    "retrieval_all",
    "retrieval_any",
    "cited_any",
    "outcome_ok",
    "tool_ok",
    "escalation_ok",
    "contains_ok",
    "not_contains_ok",
    "hard_gate_ok",
]
# Reported, but not part of auto_pass.
INFORMATIONAL = {"cited_any"}
_FLAGS = re.IGNORECASE | re.DOTALL


def category_ok(q: Question, r: dict) -> CheckResult:
    allowed = q.expect.category_any
    if not allowed:
        return None, ""
    got = r.get("category")
    return got in allowed, f"got {got}, expected one of {allowed}"


def retrieval_all(q: Question, r: dict) -> CheckResult:
    expected = q.expect.sources
    if not expected:
        return None, ""
    got = r.get("retrieved_stems") or []
    missing = [s for s in expected if s not in got]
    return not missing, f"missing {missing}; retrieved {got}"


def retrieval_any(q: Question, r: dict) -> CheckResult:
    expected = q.expect.sources
    if not expected:
        return None, ""
    got = r.get("retrieved_stems") or []
    return any(s in got for s in expected), f"none of {expected} in retrieved {got}"


def cited_any(q: Question, r: dict) -> CheckResult:
    expected = q.expect.sources
    if not expected:
        return None, ""
    got = r.get("cited_stems") or []
    return any(s in got for s in expected), f"none of {expected} in cited {got}"


def outcome_ok(q: Question, r: dict) -> CheckResult:
    turn_expectations = [
        (i, t.expect_outcome) for i, t in enumerate(q.turns) if t.expect_outcome is not None
    ]
    if not q.expect.outcome_in and not turn_expectations:
        return None, ""
    problems = []
    if q.expect.outcome_in and r.get("outcome") not in q.expect.outcome_in:
        problems.append(f"final outcome {r.get('outcome')}, expected one of {q.expect.outcome_in}")
    turns = r.get("turns") or []
    for i, expected in turn_expectations:
        got = turns[i]["outcome"] if i < len(turns) else None
        if got != expected:
            problems.append(f"turn {i + 1} outcome {got}, expected {expected}")
    return not problems, "; ".join(problems)


def tool_ok(q: Question, r: dict) -> CheckResult:
    if q.expect.tool_called is None:
        return None, ""
    got = bool(r.get("service_called"))
    return got == q.expect.tool_called, f"service called {got}, expected {q.expect.tool_called}"


def escalation_ok(q: Question, r: dict) -> CheckResult:
    if q.expect.escalated is None:
        return None, ""
    got = bool(r.get("escalated"))
    return got == q.expect.escalated, f"escalated {got}, expected {q.expect.escalated}"


def contains_ok(q: Question, r: dict) -> CheckResult:
    patterns = q.expect.must_contain
    if not patterns:
        return None, ""
    text = r.get("final_text") or ""
    missing = [p for p in patterns if not re.search(p, text, _FLAGS)]
    return not missing, f"no match for {missing}"


def not_contains_ok(q: Question, r: dict) -> CheckResult:
    patterns = q.expect.must_not_contain
    if not patterns:
        return None, ""
    text = r.get("final_text") or ""
    hits = [(p, m.group(0)) for p in patterns if (m := re.search(p, text, _FLAGS))]
    return not hits, "; ".join(f"{p!r} matched {snippet!r}" for p, snippet in hits)


def hard_gate_ok(q: Question, r: dict) -> CheckResult:
    """No '$' in any reply whose outcome forbids amounts, whatever the YAML says."""
    leaks = [
        f"turn {i + 1} ({t['outcome']})"
        for i, t in enumerate(r.get("turns") or [])
        if t.get("outcome") in NO_DOLLAR_OUTCOMES and "$" in (t.get("text") or "")
    ]
    return not leaks, f"'$' in {', '.join(leaks)}"


CHECKS = {
    "category_ok": category_ok,
    "retrieval_all": retrieval_all,
    "retrieval_any": retrieval_any,
    "cited_any": cited_any,
    "outcome_ok": outcome_ok,
    "tool_ok": tool_ok,
    "escalation_ok": escalation_ok,
    "contains_ok": contains_ok,
    "not_contains_ok": not_contains_ok,
    "hard_gate_ok": hard_gate_ok,
}


def run_checks(q: Question, record: dict, only: set[str] | None = None) -> tuple[dict, dict, bool]:
    """(checks, details, auto_pass). `only` restricts which checks are scored (others None)."""
    checks, details = {}, {}
    for name, fn in CHECKS.items():
        result, detail = fn(q, record) if (only is None or name in only) else (None, "")
        checks[name] = result
        if result is False:
            details[name] = detail
    auto_pass = record.get("error") is None and all(
        v is not False for k, v in checks.items() if k not in INFORMATIONAL
    )
    return checks, details, auto_pass
