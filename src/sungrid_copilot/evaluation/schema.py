"""Schema and loader for eval/questions.yaml (documented at the top of that file)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class EvalSetError(Exception):
    """The evaluation file is malformed."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Turn(_Strict):
    say: str = Field(min_length=1)
    expect_outcome: str | None = None


class Expect(_Strict):
    """Checks on the FINAL turn. None or empty = not scored."""

    category_any: list[str] | None = None
    sources: list[str] | None = None
    outcome_in: list[str] | None = None
    tool_called: bool | None = None
    escalated: bool | None = None


class Question(_Strict):
    id: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    turns: list[Turn] = Field(min_length=1)
    expect: Expect = Field(default_factory=Expect)
    reference: str = ""

    @property
    def text(self) -> str:
        return " || ".join(t.say for t in self.turns)


class EvalSet(_Strict):
    version: int
    questions: list[Question] = Field(min_length=1)

    @field_validator("questions")
    @classmethod
    def _unique_ids(cls, questions: list[Question]) -> list[Question]:
        ids = [q.id for q in questions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate question ids: {', '.join(duplicates)}")
        return questions


def load_eval_set(path: Path, doc_ids: set[str] | None = None) -> EvalSet:
    """Parse and validate. With `doc_ids`, expected sources must be known doc stems."""
    try:
        with path.open(encoding="utf-8") as f:
            eval_set = EvalSet.model_validate(yaml.safe_load(f) or {})
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise EvalSetError(f"Invalid evaluation file {path}: {e}") from e
    if doc_ids is not None:
        unknown = [
            f"{q.id}: {s}"
            for q in eval_set.questions
            for s in (q.expect.sources or [])
            if s not in doc_ids
        ]
        if unknown:
            raise EvalSetError(f"Unknown expected sources in {path}: {', '.join(unknown)}")
    return eval_set


def provenance_note(path: Path) -> str:
    """The `# Provenance:` comment paragraph at the top of the file, without the `#` markers."""
    lines, capturing = [], False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("#"):
            break
        text = raw.lstrip("#").strip()
        if text.startswith("Provenance:"):
            capturing = True
        elif capturing and not text:
            break
        if capturing:
            lines.append(text)
    return " ".join(lines)
