"""Load and validate `config/doc_manifest.yaml`. All doc-specific facts live in that file."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from sungrid_copilot.categories import Category


class ManifestError(Exception):
    """The manifest is malformed or out of sync with the docs directory."""


class DocEntry(BaseModel):
    file: str
    title: str
    primary: Category
    secondary: list[Category] = []
    owner: str
    note: str = ""

    @field_validator("primary")
    @classmethod
    def _primary_is_doc_category(cls, value: Category) -> Category:
        if value is Category.NON_RELEVANT:
            raise ValueError("non_relevant is a query label, not a document category")
        return value

    @field_validator("secondary")
    @classmethod
    def _secondary_are_doc_categories(cls, values: list[Category]) -> list[Category]:
        if Category.NON_RELEVANT in values:
            raise ValueError("non_relevant is a query label, not a document category")
        return values

    @model_validator(mode="after")
    def _primary_not_in_secondary(self) -> DocEntry:
        if self.primary in self.secondary:
            raise ValueError(f"primary '{self.primary.value}' is repeated in secondary")
        return self

    @property
    def doc_id(self) -> str:
        return Path(self.file).stem

    @property
    def categories(self) -> list[Category]:
        return [self.primary, *self.secondary]


def load_manifest(manifest_path: Path, docs_dir: Path) -> list[DocEntry]:
    """Parse the manifest and check it matches the `.md` files in `docs_dir` one to one."""
    try:
        with manifest_path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ManifestError(f"Cannot read manifest {manifest_path}: {e}") from e

    entries: list[DocEntry] = []
    for i, item in enumerate(raw.get("docs") or []):
        try:
            entries.append(DocEntry.model_validate(item))
        except ValidationError as e:
            name = item.get("file", f"entry #{i}") if isinstance(item, dict) else f"entry #{i}"
            raise ManifestError(f"Invalid manifest entry {name}: {e}") from e

    listed = [e.file for e in entries]
    duplicates = sorted({f for f in listed if listed.count(f) > 1})
    on_disk = {p.name for p in docs_dir.glob("*.md")}
    missing_entries = sorted(on_disk - set(listed))
    missing_files = sorted(set(listed) - on_disk)

    problems = []
    if duplicates:
        problems.append(f"listed more than once: {', '.join(duplicates)}")
    if missing_entries:
        problems.append(f"docs without a manifest entry: {', '.join(missing_entries)}")
    if missing_files:
        problems.append(f"manifest entries without a file in {docs_dir}: {', '.join(missing_files)}")
    if problems:
        raise ManifestError(f"Manifest {manifest_path} is out of sync: " + "; ".join(problems))
    return entries
