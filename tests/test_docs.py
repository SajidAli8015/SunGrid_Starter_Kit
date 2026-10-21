"""The top-level docs point at things that exist (F10 in the review of 6619e93)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINKED_DOCS = ["README.md", "NOTES.md", "eval/README.md", "submission/README.md"]


@pytest.mark.parametrize("doc", LINKED_DOCS)
def test_relative_markdown_links_resolve(doc):
    path = ROOT / doc
    targets = re.findall(r"\]\(([^)#\s]+)\)", path.read_text(encoding="utf-8"))
    missing = [t for t in targets if "://" not in t and not (path.parent / t).exists()]
    assert not missing, f"{doc} links to missing files: {missing}"


def test_readme_has_no_todo():
    assert "TODO" not in (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", ["README.md", "CLAUDE.md"])
def test_python_paths_named_in_docs_exist(doc):
    names = re.findall(r"`([\w./-]+\.py)`", (ROOT / doc).read_text(encoding="utf-8"))
    paths = [n for n in names if "/" in n]
    missing = [
        p for p in paths
        if not (ROOT / p).exists() and not (ROOT / "src" / "sungrid_copilot" / p).exists()
    ]
    assert not missing, f"{doc} names missing files: {missing}"
