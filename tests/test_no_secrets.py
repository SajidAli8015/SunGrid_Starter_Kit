"""Fail if anything in the repo looks like a real API key assignment."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".chroma", "logs"}
SKIP_FILES = {".env"}
MAX_BYTES = 2_000_000

# e.g. AZURE_OPENAI_API_KEY=abc..., "OPENAI_API_KEY": "sk-...", ANTHROPIC_API_KEY: '...'
ASSIGNMENT = re.compile(r"[A-Z0-9_]*API_KEY[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_\-+/]{16,})")
PLACEHOLDER_HINTS = ("your", "placeholder", "example", "changeme", "replace", "xxxx")


def _text_files():
    for path in REPO_ROOT.rglob("*"):
        rel = path.relative_to(REPO_ROOT)
        if not path.is_file() or path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts):
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data[:1024]:
            continue  # binary
        try:
            yield rel, data.decode("utf-8")
        except UnicodeDecodeError:
            continue


def find_suspect_assignments(text: str) -> list[int]:
    """Line numbers of suspect assignments. The matched value is never returned or printed."""
    return [
        text.count("\n", 0, m.start()) + 1
        for m in ASSIGNMENT.finditer(text)
        if not any(hint in m.group(1).lower() for hint in PLACEHOLDER_HINTS)
    ]


def test_scanner_detects_a_key_and_ignores_placeholders():
    fake_value = "Ab3" * 8
    assert find_suspect_assignments(f"OPENAI_API_KEY={fake_value}")
    assert find_suspect_assignments(f'"AZURE_OPENAI_API_KEY": "{fake_value}"')
    assert not find_suspect_assignments("AZURE_OPENAI_API_KEY=<your-azure-openai-key>")
    assert not find_suspect_assignments("OPENAI_API_KEY=your_openai_key_goes_here")
    assert not find_suspect_assignments("ANTHROPIC_API_KEY=")


def test_no_secrets_in_repo():
    hits = [
        f"{rel}:{line}" for rel, text in _text_files() for line in find_suspect_assignments(text)
    ]
    assert not hits, "Possible secrets found:\n" + "\n".join(hits)
