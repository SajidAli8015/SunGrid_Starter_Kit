"""End-to-end eval runs offline: scripted fake LLM, hash-embedder KB, the real stub."""

import json

import pytest
import yaml

from agent_helpers import FULL_SLOTS, MESSAGES, Harness, answer, build_kb, label, m, q
from sungrid_copilot.answer import AnswerComposer
from sungrid_copilot.evaluation.full_context import run_full_context
from sungrid_copilot.evaluation.runner import run_eval
from sungrid_copilot.evaluation.schema import EvalSet
from sungrid_copilot.kb.store import Chunk
from sungrid_copilot.llm import LLMError
from sungrid_copilot.llm.fake import FakeLLMClient
from sungrid_copilot.usage import TrackedLLM, UsageTracker

BILL_Q = "How are monthly bill charges explained?"
ELIG_Q = "do I qualify? 94103, 85k/yr, 7.5 kW, approved installer, household"
POEM_Q = "Write a poem about the sea."
TITLE_TO_STEM = {"Bills": "bills", "Faults": "faults", "Rebate": "rebate"}

EVAL_SET = EvalSet.model_validate(yaml.safe_load(f"""
version: 1
questions:
  - id: e1
    tags: [billing_account]
    turns: [{{say: "{BILL_Q}"}}]
    expect: {{category_any: [billing_account], sources: [bills], outcome_in: [answered],
              tool_called: false}}
  - id: e2
    tags: [eligibility, eligible]
    turns: [{{say: "{ELIG_Q}"}}]
    expect: {{outcome_in: [eligible_preliminary], tool_called: true}}
  - id: e3
    tags: [non_relevant]
    turns: [{{say: "{POEM_Q}"}}]
    expect: {{category_any: [non_relevant], outcome_in: [declined_out_of_scope], tool_called: false}}
"""))


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    return build_kb(tmp_path_factory.mktemp("kb"))


def _fakes(classifier=None):
    classifier = classifier or FakeLLMClient({
        q(BILL_Q): label("billing_account"),
        q(ELIG_Q): label("incentive_rebate", 0.95, True),
        q(POEM_Q): label("non_relevant", 0.99),
    })
    extractor = FakeLLMClient({m(ELIG_Q): json.dumps(FULL_SLOTS)})
    composer = FakeLLMClient({q(BILL_Q): answer("Charges are explained monthly.")},
                             default=answer("Submit your documents."))
    return classifier, extractor, composer


def _factory(kb, tmp_path, fakes):
    return lambda: Harness(kb, tmp_path, *fakes).agent


def test_three_questions_end_to_end(kb, tmp_path):
    records = run_eval(EVAL_SET.questions, _factory(kb, tmp_path, _fakes()), TITLE_TO_STEM, workers=2)
    by_id = {r["id"]: r for r in records}
    assert [r["id"] for r in records] == ["e1", "e2", "e3"]
    assert all(r["auto_pass"] for r in records), {r["id"]: r["check_details"] for r in records}

    e1 = by_id["e1"]
    assert e1["category"] == "billing_account" and e1["retrieved_stems"][0] == "bills"
    assert e1["cited_stems"] == ["bills"] and e1["llm_call_count"] == 2
    assert e1["tokens_in"] == sum(c["input_tokens"] for c in e1["llm_calls"]) > 0
    assert [step["name"] for step in e1["turns"][0]["trace"]] == ["classify", "retrieve", "compose_answer"]

    e2 = by_id["e2"]
    assert e2["service_called"] and e2["gate_verdict"] == "ELIGIBLE_PRELIMINARY"
    assert "$3,000.00" in e2["final_text"]
    assert by_id["e3"]["outcome"] == "declined_out_of_scope" and not by_id["e3"]["service_called"]


def test_provider_error_on_one_question_is_recorded_and_run_completes(kb, tmp_path):
    class FailOnPoem(FakeLLMClient):
        def _complete(self, system, messages, **kw):
            if POEM_Q in messages[-1]["content"]:
                raise LLMError("provider down")
            return super()._complete(system, messages, **kw)

    classifier = FailOnPoem({q(BILL_Q): label("billing_account"),
                             q(ELIG_Q): label("incentive_rebate", 0.95, True)})
    records = run_eval(EVAL_SET.questions, _factory(kb, tmp_path, _fakes(classifier)),
                       TITLE_TO_STEM, workers=1)
    by_id = {r["id"]: r for r in records}
    assert by_id["e3"]["error"].startswith("provider failure")
    assert by_id["e3"]["auto_pass"] is False
    assert by_id["e1"]["auto_pass"] and by_id["e2"]["auto_pass"]


def test_crash_in_agent_is_recorded(kb, tmp_path):
    class Broken:
        def handle(self, text, session):
            raise RuntimeError("index exploded")

    records = run_eval(EVAL_SET.questions[:1], lambda: Broken(), TITLE_TO_STEM, workers=1)
    assert records[0]["error"] == "RuntimeError: index exploded" and records[0]["auto_pass"] is False


def test_agent_setup_failure_is_recorded(kb, tmp_path):
    def factory():
        raise RuntimeError("no index")

    records = run_eval(EVAL_SET.questions[:2], factory, TITLE_TO_STEM, workers=1)
    assert all(r["error"].startswith("agent setup failed") for r in records)


def test_repeat_runs_each_question_n_times(kb, tmp_path):
    records = run_eval(EVAL_SET.questions[:1], _factory(kb, tmp_path, _fakes()), TITLE_TO_STEM,
                       workers=1, repeat=3)
    assert [r["repeat"] for r in records] == [1, 2, 3]


def test_full_context_baseline_skips_eligibility_and_non_relevant():
    chunks = [Chunk("bills::00", "bills", "Bills", "Charges", "Monthly bill charges explained.",
                    "billing_account", [], "docs/bills.md", "h", "t")]
    composer_llm = FakeLLMClient(default=answer("Charges are explained monthly."))

    def factory():
        usage = UsageTracker()
        return AnswerComposer(TrackedLLM(composer_llm, "answerer", usage)), usage

    records = run_full_context(EVAL_SET.questions, factory, chunks, MESSAGES, TITLE_TO_STEM, workers=1)
    by_id = {r["id"]: r for r in records}
    assert by_id["e2"]["skipped"] and by_id["e3"]["skipped"]
    e1 = by_id["e1"]
    assert e1["mode"] == "full-context" and e1["auto_pass"] is True
    assert e1["checks"]["outcome_ok"] is True and e1["checks"]["cited_ok"] is True
    assert e1["checks"]["retrieval_ok"] is None and e1["checks"]["category_ok"] is None
    assert e1["checks"]["tool_ok"] is None and e1["checks"]["escalation_ok"] is None
    assert e1["cited_stems"] == ["bills"]
    assert len(composer_llm.calls) == 1
    assert "[S1] Bills > Charges" in composer_llm.calls[0].messages[0]["content"]
