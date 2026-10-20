"""Vector store and ingestion with the HashEmbedder: no network, no model download."""

import pytest

from kb_helpers import entry, write_kb
from sungrid_copilot.config import Settings
from sungrid_copilot.kb.embeddings import HashEmbedder
from sungrid_copilot.kb.ingest import ingest
from sungrid_copilot.kb.search import search
from sungrid_copilot.kb.store import ChromaVectorStore, IndexNotReadyError

DOCS = {
    "refunds.md": "# Refunds\n\nIntro about reversals.\n\n## Reversal\nRebate reversal repayment schedule.\n",
    "bills.md": "# Bills\n## Charges\nMonthly bill charges explained.\n",
    "faults.md": "# Faults\n## Codes\nInverter fault code steps.\n",
}


@pytest.fixture
def kb_settings(tmp_path):
    manifest, docs_dir = write_kb(
        tmp_path,
        DOCS,
        [
            entry("refunds.md", "incentive_rebate", ["billing_account"]),
            entry("bills.md", "billing_account"),
            entry("faults.md", "technical_installation"),
        ],
    )
    return Settings.model_validate(
        {
            "vector_store": {"path": tmp_path / "chroma", "collection": "test_kb"},
            "ingestion": {"docs_dir": docs_dir, "manifest": manifest},
        }
    )


def _doc_ids(settings, query, category=None):
    hits = search(settings, query, top_k=10, category=category, embedder=HashEmbedder())
    return {h.chunk.doc_id for h in hits}


def test_ingest_counts_and_is_idempotent(kb_settings):
    first = ingest(kb_settings, HashEmbedder())
    second = ingest(kb_settings, HashEmbedder())
    assert first == second == {"refunds": 2, "bills": 1, "faults": 1}
    store = ChromaVectorStore.open(
        kb_settings.vector_store.path, "test_kb", HashEmbedder().model_name
    )
    assert store.count() == 4


def test_secondary_category_doc_found_under_both_categories_and_unfiltered(kb_settings):
    ingest(kb_settings, HashEmbedder())
    assert "refunds" in _doc_ids(kb_settings, "rebate reversal")
    assert "refunds" in _doc_ids(kb_settings, "rebate reversal", "incentive_rebate")
    assert "refunds" in _doc_ids(kb_settings, "rebate reversal", "billing_account")


def test_doc_without_secondary_only_under_primary(kb_settings):
    ingest(kb_settings, HashEmbedder())
    assert _doc_ids(kb_settings, "bill charges", "billing_account") == {"refunds", "bills"}
    assert "bills" not in _doc_ids(kb_settings, "bill charges", "incentive_rebate")
    assert _doc_ids(kb_settings, "inverter", "technical_installation") == {"faults"}
    assert _doc_ids(kb_settings, "anything", "company_updates") == set()


def test_hits_carry_metadata_and_scores(kb_settings):
    ingest(kb_settings, HashEmbedder())
    hits = search(kb_settings, "Rebate reversal repayment schedule", top_k=4, embedder=HashEmbedder())
    top = hits[0]
    assert top.chunk.doc_id == "refunds"
    assert top.chunk.section == "Reversal"
    assert top.chunk.secondary == ["billing_account"]
    assert top.chunk.text == "Rebate reversal repayment schedule."
    assert top.chunk.source_path.endswith("refunds.md")
    assert len(top.chunk.content_hash) == 16
    assert hits == sorted(hits, key=lambda h: h.score, reverse=True)
    assert 0 < top.score <= 1.0001


def test_model_mismatch_fails_loudly(kb_settings):
    ingest(kb_settings, HashEmbedder(dim=256))
    with pytest.raises(IndexNotReadyError, match="hash-bow-256.*hash-bow-128.*ingest"):
        search(kb_settings, "rebate", embedder=HashEmbedder(dim=128))


def test_missing_index_fails_loudly(kb_settings):
    with pytest.raises(IndexNotReadyError, match="ingest"):
        search(kb_settings, "rebate", embedder=HashEmbedder())
