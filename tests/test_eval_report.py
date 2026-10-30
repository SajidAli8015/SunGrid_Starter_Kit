import csv

import pytest

from sungrid_copilot.evaluation.report import (
    GradeError,
    build_summary,
    check_counts,
    load_results,
    merge_grades,
    write_outputs,
)
from sungrid_copilot.evaluation.schema import EvalSet

EVAL_SET = EvalSet.model_validate(
    {
        "version": 1,
        "questions": [
            {"id": "q1", "tags": ["billing_account"], "turns": [{"say": "Bill?"}], "reference": "21 days"},
            {"id": "q2", "tags": ["billing_account", "trap"], "turns": [{"say": "Autopay?"}]},
            {"id": "q3", "tags": ["non_relevant"], "turns": [{"say": "Poem?"}]},
        ],
    }
)
META = {
    "date_utc": "2026-10-21T10:00:00+00:00", "git_commit": "abc123", "git_dirty": False,
    "mode": "pipeline", "repeat": 1, "workers": 3, "provider": "azure_openai", "model": "gpt-4o",
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "retrieval": {"top_k": 5, "classifier_min_conf": 0.6, "non_relevant_min_conf": 0.85,
                  "fallback_margin": 0.04, "non_relevant_score_ceiling": 0.6},
    "classifier": {"max_tokens": 200}, "llm_cache": False, "questions_file": "eval/questions.yaml",
    "questions_sha256": "0" * 64, "provenance": "Provenance: written after the demos.",
}


def rec(qid, tags, auto_pass, checks, details=None, outcome="answered", cost=None, **kw):
    return {
        "id": qid, "tags": tags, "repeat": 1, "auto_pass": auto_pass, "checks": checks,
        "check_details": details or {}, "outcome": outcome, "error": None, "latency_ms": 1000.0,
        "llm_call_count": 2, "tokens_in": 100, "tokens_out": 10, "estimated_cost_usd": cost,
        "final_text": f"answer {qid}", "cited_stems": ["03_billing"], **kw,
    }


RECORDS = [
    rec("q1", ["billing_account"], True, {"cited_ok": True, "hard_gate_ok": True}),
    rec("q2", ["billing_account", "trap"], False, {"cited_ok": False, "hard_gate_ok": True},
        {"cited_ok": "none of ['12_autopay'] in cited []"}),
    rec("q3", ["non_relevant"], True, {"hard_gate_ok": True}, outcome="declined_out_of_scope"),
]


def test_counts_use_only_scored_checks():
    counts = check_counts(RECORDS)
    assert counts["cited_ok"] == (1, 2)
    assert counts["hard_gate_ok"] == (3, 3)
    assert counts["auto_pass"] == (2, 3)
    assert counts["tool_ok"] == (0, 0)


def test_summary_has_header_counts_tags_and_failing_detail():
    s = build_summary(META, RECORDS, EVAL_SET)
    assert "`abc123` (working tree dirty: no)" in s
    assert "fallback_margin=0.04" in s and "Provenance: written after the demos." in s
    assert "| cited_ok | 1/2 |" in s and "| **auto_pass** | **2/3** |" in s
    assert "| tool_ok | n/a |" in s
    assert "| trap | 0/1 |" in s and "| billing_account | 1/2 |" in s
    assert "**q2** (billing_account, trap)" in s and "none of ['12_autopay'] in cited []" in s
    assert "not a rate" in s and "%" not in s.split("## Automated checks")[1]
    assert "| answered | 2 |" in s
    assert "do not score the content of the reply" in s
    assert "| escalation_ok | n/a |" in s
    for removed in ("contains_ok", "retrieval_any", "informational"):
        assert removed not in s


def test_cost_lines_omitted_without_pricing_and_shown_with_it():
    assert "Estimated cost" not in build_summary(META, RECORDS, EVAL_SET)
    priced = [r | {"estimated_cost_usd": 0.002} for r in RECORDS]
    s = build_summary(META, priced, EVAL_SET)
    assert "Estimated cost: $0.0060 total" in s and "$2.00 per 1,000 queries" in s


def test_stability_section_for_repeats():
    second = [r | {"repeat": 2} for r in RECORDS]
    second[1] = second[1] | {"outcome": "abstained"}
    s = build_summary(META | {"repeat": 2}, RECORDS + second, EVAL_SET)
    assert "Same outcome and same auto_pass in every repeat: 2/3" in s
    assert "unstable q2" in s


def _fill(path, grades):
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row.update(grades.get(row["id"], {}))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_grade_sheet_round_trip_and_merge(tmp_path):
    write_outputs(tmp_path, META, RECORDS, EVAL_SET)
    meta, records = load_results(tmp_path)
    assert meta["git_commit"] == "abc123" and len(records) == 3
    with (tmp_path / "grade_sheet.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["id"] for r in rows] == ["q1", "q2", "q3"]
    assert rows[0]["reference"] == "21 days" and rows[1]["failed_checks"] == "cited_ok"
    assert rows[0]["correct"] == rows[0]["grounded"] == rows[0]["notes"] == ""

    sheet = tmp_path / "grade_sheet.csv"
    _fill(sheet, {"q1": {"correct": "1", "grounded": "1"},
                  "q2": {"correct": "0", "grounded": "1", "notes": "missed the original due date"},
                  "q3": {"correct": "1", "grounded": "n/a"}})
    text = merge_grades(tmp_path, sheet)
    assert "- correct: 2/3" in text and "- grounded: 2/2" in text
    assert "- q2 (correct): missed the original due date" in text
    # Re-merging replaces the section instead of appending a second one.
    _fill(sheet, {"q2": {"correct": "1"}})
    text = merge_grades(tmp_path, sheet)
    assert text.count("## Hand grading") == 1 and "- correct: 3/3" in text


def test_merge_rejects_bad_grades(tmp_path):
    write_outputs(tmp_path, META, RECORDS, EVAL_SET)
    sheet = tmp_path / "grade_sheet.csv"
    _fill(sheet, {"q1": {"correct": "yes"}})
    with pytest.raises(GradeError, match="correct must be 0, 1"):
        merge_grades(tmp_path, sheet)
