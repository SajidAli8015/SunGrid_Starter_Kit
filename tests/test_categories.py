import pytest

from kb_helpers import category, entry, write_categories, write_kb
from sungrid_copilot.categories import NON_RELEVANT, CategoryError, load_categories
from sungrid_copilot.config import load_settings
from sungrid_copilot.kb.manifest import ManifestError, load_manifest


def test_real_categories_file_loads():
    categories = load_categories(load_settings().categories.resolved_file)
    assert categories.names == [
        "program_policies",
        "incentive_rebate",
        "billing_account",
        "technical_installation",
        "company_updates",
    ]
    assert categories.query_labels[-1] == NON_RELEVANT


def test_new_category_needs_only_yaml(tmp_path):
    """A category added in YAML is accepted by the manifest with no code change."""
    path = write_categories(tmp_path, [category("billing_account"), category("ev_charging")])
    categories = load_categories(path)
    manifest, docs_dir = write_kb(
        tmp_path,
        {"chargers.md": "# Chargers\n## Home\nText.\n", "bills.md": "# Bills\n## A\nText.\n"},
        [entry("chargers.md", "ev_charging", ["billing_account"]), entry("bills.md", "billing_account")],
    )
    entries = load_manifest(manifest, docs_dir, categories)
    assert entries[0].categories == ["ev_charging", "billing_account"]
    assert "ev_charging" in categories.query_labels


def test_category_removed_from_yaml_is_rejected_by_manifest(tmp_path):
    categories = load_categories(write_categories(tmp_path, [category("billing_account")]))
    manifest, docs_dir = write_kb(
        tmp_path, {"a.md": "# A\n## S\nText.\n"}, [entry("a.md", "incentive_rebate")]
    )
    with pytest.raises(ManifestError, match="incentive_rebate"):
        load_manifest(manifest, docs_dir, categories)


@pytest.mark.parametrize(
    "categories, message",
    [
        ([category(NON_RELEVANT)], "reserved"),
        ([category("a_b"), category("a_b")], "duplicate"),
        ([category("Not Snake")], "pattern"),
        ([], "at least 1"),
    ],
)
def test_bad_categories_file_is_rejected(tmp_path, categories, message):
    with pytest.raises(CategoryError, match=message):
        load_categories(write_categories(tmp_path, categories))


def test_require_rejects_unknown_and_non_relevant(tmp_path):
    categories = load_categories(write_categories(tmp_path, [category("billing_account")]))
    assert categories.require("billing_account") == "billing_account"
    with pytest.raises(CategoryError, match="Unknown category 'nope'"):
        categories.require("nope")
    with pytest.raises(CategoryError, match="query label only"):
        categories.require(NON_RELEVANT)
