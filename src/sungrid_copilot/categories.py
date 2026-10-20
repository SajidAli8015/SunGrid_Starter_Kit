"""Query/document categories, loaded from `config/categories.yaml` (the single source of truth).

Category values are plain validated strings, so adding a category needs only a YAML edit plus
manifest entries. `non_relevant` is a built-in reserved query label, never a document category.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

NON_RELEVANT = "non_relevant"
_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"  # snake_case; also safe inside a store metadata key


class CategoryError(Exception):
    """The categories file is malformed, or a value is not a known category."""


class CategoryDef(BaseModel):
    name: str = Field(pattern=_NAME_PATTERN)
    display_name: str
    description: str
    examples: list[str] = Field(min_length=1)


class CategorySet(BaseModel):
    categories: list[CategoryDef] = Field(min_length=1)

    @field_validator("categories")
    @classmethod
    def _unique_and_not_reserved(cls, values: list[CategoryDef]) -> list[CategoryDef]:
        names = [c.name for c in values]
        if NON_RELEVANT in names:
            raise ValueError(f"'{NON_RELEVANT}' is reserved and must not be listed")
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"duplicate category names: {', '.join(duplicates)}")
        return values

    @property
    def names(self) -> list[str]:
        """Document (in-scope) categories, in file order."""
        return [c.name for c in self.categories]

    @property
    def query_labels(self) -> list[str]:
        """Labels the classifier may return: every category plus `non_relevant`."""
        return [*self.names, NON_RELEVANT]

    def require(self, name: str) -> str:
        """Return `name` if it is a document category, else raise CategoryError."""
        if name not in self.names:
            hint = " (non_relevant is a query label only)" if name == NON_RELEVANT else ""
            raise CategoryError(
                f"Unknown category '{name}'{hint}. Known categories: {', '.join(self.names)}."
            )
        return name


def load_categories(path: Path) -> CategorySet:
    try:
        with path.open(encoding="utf-8") as f:
            return CategorySet.model_validate(yaml.safe_load(f) or {})
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise CategoryError(f"Invalid categories file {path}: {e}") from e
