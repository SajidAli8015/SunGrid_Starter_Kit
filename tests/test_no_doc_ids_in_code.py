"""Doc-specific facts live only in the manifest: no doc file names or IDs in src/."""

import re
from pathlib import Path

from sungrid_copilot.categories import load_categories
from sungrid_copilot.config import load_settings
from sungrid_copilot.kb.manifest import load_manifest

SRC = Path(__file__).resolve().parents[1] / "src"


def _forbidden_patterns() -> list[tuple[str, re.Pattern]]:
    settings = load_settings()
    entries = load_manifest(
        settings.ingestion.resolved_manifest,
        settings.ingestion.resolved_docs_dir,
        load_categories(settings.categories.resolved_file),
    )
    patterns = []
    for e in entries:
        stem = Path(e.file).stem
        patterns.append((e.file, re.compile(re.escape(e.file))))
        patterns.append((stem, re.compile(re.escape(stem))))
        prefix = re.match(r"\d+_", stem)
        if prefix:  # e.g. "06_" anywhere that is not part of a longer number or word
            patterns.append((prefix.group(0), re.compile(rf"(?<![\w.]){re.escape(prefix.group(0))}")))
    return patterns


def test_no_doc_names_in_source():
    patterns = _forbidden_patterns()
    hits = []
    for path in SRC.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label, pattern in patterns:
                if pattern.search(line):
                    hits.append(f"{path.relative_to(SRC.parent).as_posix()}:{lineno} contains {label!r}")
    assert not hits, "Doc identifiers found in source:\n" + "\n".join(hits)
