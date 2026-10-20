"""Calibration end to end with the fake LLM, hash embedder and a temp Chroma index."""

import json

import pytest
import yaml

from kb_helpers import entry, write_kb
from sungrid_copilot.calibrate import format_summary, load_dev_set, run_calibration
from sungrid_copilot.categories import load_categories
from sungrid_copilot.classify import Classifier
from sungrid_copilot.cli import DEFAULT_DEV_SET
from sungrid_copilot.config import Settings, load_settings
from sungrid_copilot.kb.embeddings import HashEmbedder
from sungrid_copilot.kb.ingest import ingest
from sungrid_copilot.kb.manifest import load_manifest
from sungrid_copilot.llm.fake import FakeLLMClient
from sungrid_copilot.retrieval import Retriever

CATEGORIES = load_categories(load_settings().categories.resolved_file)
DEV = {
    "queries": [
        {"id": "q1", "query": "inverter fault code", "expected_category": "technical_installation",
         "expected_sources": ["faults"]},
        {"id": "q2", "query": "monthly bill charges", "expected_category": "billing_account",
         "expected_sources": ["bills"]},
        {"id": "q3", "query": "poem about the sea", "expected_category": "non_relevant"},
    ]
}


def _label(category):
    return json.dumps(
        {"category": category, "confidence": 0.9, "needs_eligibility_check": False, "rationale": "t"}
    )


@pytest.fixture
def setup(tmp_path):
    manifest, docs_dir = write_kb(
        tmp_path,
        {
            "faults.md": "# Faults\n## Codes\nInverter fault code steps.\n",
            "bills.md": "# Bills\n## Charges\nMonthly bill charges explained.\n",
        },
        [entry("faults.md", "technical_installation"), entry("bills.md", "billing_account")],
    )
    settings = Settings.model_validate(
        {
            "vector_store": {"path": tmp_path / "chroma", "collection": "test_kb"},
            "ingestion": {"docs_dir": docs_dir, "manifest": manifest},
        }
    )
    ingest(settings, HashEmbedder())
    dev_path = tmp_path / "dev.yaml"
    dev_path.write_text(yaml.safe_dump(DEV), encoding="utf-8")
    queries = load_dev_set(dev_path, CATEGORIES, {"faults", "bills"})
    # Keys are full queries: the fake also matches on the system prompt, which mentions
    # words like "inverter" and "bill".
    client = FakeLLMClient(
        {
            "inverter fault code": _label("technical_installation"),
            "monthly bill charges": _label("company_updates"),
            "poem about the sea": _label("non_relevant"),
        }
    )
    classifier = Classifier(client, CATEGORIES, cache_dir=tmp_path / "cache")
    retriever = Retriever.from_settings(settings, embedder=HashEmbedder())
    return classifier, retriever, queries, client


def test_calibration_reports_counts_and_second_run_uses_cache(setup):
    classifier, retriever, queries, client = setup
    report = run_calibration(classifier, retriever, queries, workers=2)
    c = report["classification"]
    assert (c["category_correct"], c["n"]) == (2, 3)
    assert c["misses"][0]["id"] == "q2" and c["misses"][0]["got"] == "company_updates"
    assert c["llm_calls"] == 3
    rc = report["robustness_current"]
    assert rc["a_correct_category"] == {"hits": 2, "n": 2, "fallback_fired": 0}
    assert rc["b_wrong_with_fallback"]["n"] == rc["c_wrong_without_fallback"]["n"] == 8
    assert len(report["margin_sweep"]) == 9
    assert "fallback_margin" in report["suggested"]
    assert "2/3 correct" in format_summary(report)

    again = run_calibration(classifier, retriever, queries, workers=2)
    assert again["classification"]["llm_calls"] == 0
    assert again["classification"]["cached"] == 3
    assert len(client.calls) == 3


def test_dev_set_rejects_unknown_category_and_source(tmp_path):
    bad = {"queries": [
        {"id": "x", "query": "q", "expected_category": "weather", "expected_sources": ["nope"]},
    ]}
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown category 'weather'.*unknown source 'nope'"):
        load_dev_set(path, CATEGORIES, {"faults"})


def test_real_dev_set_is_valid():
    settings = load_settings()
    entries = load_manifest(
        settings.ingestion.resolved_manifest, settings.ingestion.resolved_docs_dir, CATEGORIES
    )
    queries = load_dev_set(DEFAULT_DEV_SET, CATEGORIES, {e.doc_id for e in entries})
    assert len(queries) == 28
    assert sum(q.in_scope for q in queries) == 20
    for name in CATEGORIES.names:
        assert sum(q.expected_category == name for q in queries) >= 3
