import pytest

from kb_helpers import entry, write_kb
from sungrid_copilot.config import load_settings
from sungrid_copilot.kb.manifest import ManifestError, load_manifest

DOCS = {"alpha.md": "# Alpha\n## A\nText.\n", "beta.md": "# Beta\n## B\nText.\n"}


def test_valid_manifest_loads(tmp_path):
    manifest, docs_dir = write_kb(
        tmp_path, DOCS, [entry("alpha.md", "billing_account"), entry("beta.md", "incentive_rebate")]
    )
    entries = load_manifest(manifest, docs_dir)
    assert [e.doc_id for e in entries] == ["alpha", "beta"]


def test_doc_without_entry_is_rejected(tmp_path):
    manifest, docs_dir = write_kb(tmp_path, DOCS, [entry("alpha.md", "billing_account")])
    with pytest.raises(ManifestError, match="without a manifest entry: beta.md"):
        load_manifest(manifest, docs_dir)


def test_entry_without_file_is_rejected(tmp_path):
    entries = [
        entry("alpha.md", "billing_account"),
        entry("beta.md", "billing_account"),
        entry("gamma.md", "billing_account"),
    ]
    manifest, docs_dir = write_kb(tmp_path, DOCS, entries)
    with pytest.raises(ManifestError, match="without a file .*gamma.md"):
        load_manifest(manifest, docs_dir)


def test_unknown_category_is_rejected(tmp_path):
    entries = [entry("alpha.md", "billing"), entry("beta.md", "billing_account")]
    manifest, docs_dir = write_kb(tmp_path, DOCS, entries)
    with pytest.raises(ManifestError, match="alpha.md"):
        load_manifest(manifest, docs_dir)


@pytest.mark.parametrize(
    "bad", [entry("alpha.md", "non_relevant"), entry("alpha.md", "billing_account", ["non_relevant"])]
)
def test_non_relevant_is_rejected(tmp_path, bad):
    manifest, docs_dir = write_kb(tmp_path, DOCS, [bad, entry("beta.md", "billing_account")])
    with pytest.raises(ManifestError, match="non_relevant"):
        load_manifest(manifest, docs_dir)


def test_primary_repeated_in_secondary_is_rejected(tmp_path):
    entries = [
        entry("alpha.md", "billing_account", ["billing_account"]),
        entry("beta.md", "billing_account"),
    ]
    manifest, docs_dir = write_kb(tmp_path, DOCS, entries)
    with pytest.raises(ManifestError, match="repeated in secondary"):
        load_manifest(manifest, docs_dir)


def test_duplicate_entry_is_rejected(tmp_path):
    entries = [
        entry("alpha.md", "billing_account"),
        entry("alpha.md", "billing_account"),
        entry("beta.md", "billing_account"),
    ]
    manifest, docs_dir = write_kb(tmp_path, DOCS, entries)
    with pytest.raises(ManifestError, match="more than once"):
        load_manifest(manifest, docs_dir)


def test_real_manifest_matches_real_docs():
    settings = load_settings()
    entries = load_manifest(settings.ingestion.resolved_manifest, settings.ingestion.resolved_docs_dir)
    assert len(entries) == len(list(settings.ingestion.resolved_docs_dir.glob("*.md")))
