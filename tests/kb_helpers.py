"""Build a tiny synthetic knowledge base on disk for tests."""

from pathlib import Path

import yaml


def write_kb(root: Path, docs: dict[str, str], entries: list[dict]) -> tuple[Path, Path]:
    """Write markdown files and a manifest. Returns (manifest_path, docs_dir)."""
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        (docs_dir / name).write_text(text, encoding="utf-8")
    manifest = root / "doc_manifest.yaml"
    manifest.write_text(yaml.safe_dump({"docs": entries}), encoding="utf-8")
    return manifest, docs_dir


def entry(file: str, primary: str, secondary: list[str] | None = None) -> dict:
    return {
        "file": file,
        "title": file.removesuffix(".md").title(),
        "primary": primary,
        "secondary": secondary or [],
        "owner": "Test team",
        "note": "",
    }
