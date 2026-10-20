"""Split a markdown document into `##` sections, keeping tables and lists intact.

Generic rules only (nothing doc-specific):
- Text between the H1 and the first `##` becomes a section called "Introduction".
- A section over `max_tokens` is split on paragraph boundaries, then on bullet boundaries if a
  single list is still too long. Tables are never split.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INTRODUCTION = "Introduction"
_H1_RE = re.compile(r"^#\s+")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TOKEN_RE = re.compile(r"\w+|[^\w\s]")


@dataclass(frozen=True)
class Section:
    heading: str
    body: str


def estimate_tokens(text: str) -> int:
    """Rough token count (words plus punctuation); close enough for a size limit."""
    return len(_TOKEN_RE.findall(text))


def split_sections(markdown: str, max_tokens: int) -> list[Section]:
    sections: list[Section] = []
    heading = INTRODUCTION
    lines: list[str] = []
    title_skipped = False

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.extend(_split_oversize(heading, body, max_tokens))

    for line in markdown.splitlines():
        h2 = _H2_RE.match(line)
        if h2:
            flush()
            heading, lines = h2.group(1), []
        elif _H1_RE.match(line) and not title_skipped and heading == INTRODUCTION:
            title_skipped = True  # the document title; the manifest title is prefixed instead
        else:
            lines.append(line)
    flush()
    return sections


def _split_oversize(heading: str, body: str, max_tokens: int) -> list[Section]:
    if estimate_tokens(body) <= max_tokens:
        return [Section(heading, body)]

    units: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if estimate_tokens(block) > max_tokens and _is_list(block):
            units.extend(_bullet_items(block))
        else:
            units.append(block)  # paragraphs and tables stay whole even if large

    parts: list[str] = []
    current: list[str] = []
    for unit in units:
        if current and estimate_tokens("\n\n".join([*current, unit])) > max_tokens:
            parts.append("\n\n".join(current))
            current = []
        current.append(unit)
    if current:
        parts.append("\n\n".join(current))

    if len(parts) == 1:
        return [Section(heading, parts[0])]
    return [Section(f"{heading} (part {i}/{len(parts)})", p) for i, p in enumerate(parts, 1)]


def _is_list(block: str) -> bool:
    return bool(_BULLET_RE.match(block.splitlines()[0]))


def _bullet_items(block: str) -> list[str]:
    """Split a list into items; indented continuation lines stay with their bullet."""
    items: list[list[str]] = []
    for line in block.splitlines():
        if not items or (_BULLET_RE.match(line) and not line.startswith((" ", "\t"))):
            items.append([line])
        else:
            items[-1].append(line)
    return ["\n".join(item) for item in items]
