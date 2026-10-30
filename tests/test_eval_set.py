"""eval/questions.yaml meets the brief's coverage requirements (and stays separate from the dev set)."""

from pathlib import Path

import pytest
import yaml

from sungrid_copilot.categories import load_categories
from sungrid_copilot.config import load_settings
from sungrid_copilot.evaluation.schema import load_eval_set, provenance_note
from sungrid_copilot.kb.manifest import load_manifest

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "questions.yaml"
DEV = ROOT / "eval" / "dev_queries.yaml"
AMBIGUOUS_DOC = "06_ambiguous_rebate_billing_adjustments"


@pytest.fixture(scope="module")
def questions():
    settings = load_settings()
    entries = load_manifest(
        settings.ingestion.resolved_manifest,
        settings.ingestion.resolved_docs_dir,
        load_categories(settings.categories.resolved_file),
    )
    return load_eval_set(QUESTIONS, {e.doc_id for e in entries}).questions


def tagged(questions, tag):
    return [q for q in questions if tag in q.tags]


def test_size(questions):
    assert 15 <= len(questions) <= 20


def test_ids_unique(questions):
    ids = [q.id for q in questions]
    assert len(ids) == len(set(ids))


def test_every_category_is_covered(questions):
    covered = {c for q in questions for c in (q.expect.category_any or [])}
    for category in load_categories(load_settings().categories.resolved_file).names:
        assert category in covered, category


def test_ambiguous_doc_questions(questions):
    hits = [q for q in tagged(questions, "ambiguous_doc") if AMBIGUOUS_DOC in (q.expect.sources or [])]
    assert len(hits) >= 2


def test_eligibility_questions_include_an_ineligible_case(questions):
    eligibility = tagged(questions, "eligibility")
    assert len(eligibility) >= 3
    assert any("ineligible" in q.tags for q in eligibility)


def test_non_relevant_questions(questions):
    assert len(tagged(questions, "non_relevant")) >= 2


def test_no_question_is_copied_from_the_dev_set(questions):
    dev_texts = {
        q["query"].strip().lower()
        for q in yaml.safe_load(DEV.read_text(encoding="utf-8"))["queries"]
    }
    for q in questions:
        for turn in q.turns:
            assert turn.say.strip().lower() not in dev_texts, q.id


def test_provenance_says_the_set_is_not_blind():
    note = provenance_note(QUESTIONS)
    assert "so it is not blind" in note and "not an accuracy benchmark" in note


def test_every_question_says_what_it_tests():
    lines = QUESTIONS.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("  - id: "):
            qid = line.split()[-1]
            block = [x for x in lines[max(0, i - 3):i] if x.lstrip().startswith("#")]
            assert any(x.startswith(f"  # {qid} | TESTS: ") for x in block), qid
            assert any("| PASS MEANS: " in x for x in block), qid


def test_only_q02_and_q09_expect_a_review_flag(questions):
    flagged = {q.id: q.expect.escalated for q in questions if q.expect.escalated is not None}
    assert flagged == {"q02": True, "q09": True}
