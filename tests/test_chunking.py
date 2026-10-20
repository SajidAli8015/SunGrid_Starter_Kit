from sungrid_copilot.kb.chunking import INTRODUCTION, estimate_tokens, split_sections
from sungrid_copilot.kb.store import Chunk

DOC = """# Example Org — Sample Doc

This preamble sits before any section.

## Fees
Fees depend on tier.

| Tier | Fee |
|---|---|
| A | $1 |
| B | $2 |

## Empty

## Steps
- first step
- second step
"""


def test_preamble_becomes_introduction_and_title_is_dropped():
    sections = split_sections(DOC, max_tokens=350)
    assert sections[0].heading == INTRODUCTION
    assert sections[0].body == "This preamble sits before any section."
    assert all("Sample Doc" not in s.body for s in sections)


def test_sections_split_on_h2_and_empty_sections_skipped():
    assert [s.heading for s in split_sections(DOC, max_tokens=350)] == [
        INTRODUCTION,
        "Fees",
        "Steps",
    ]


def test_table_kept_intact():
    fees = next(s for s in split_sections(DOC, max_tokens=350) if s.heading == "Fees")
    assert "| Tier | Fee |\n|---|---|\n| A | $1 |\n| B | $2 |" in fees.body


def test_no_preamble_means_no_introduction():
    sections = split_sections("# Title\n## Only\nBody text.\n", max_tokens=350)
    assert [s.heading for s in sections] == ["Only"]


def test_oversize_section_split_on_paragraphs():
    paragraphs = [" ".join(f"p{i}w{j}" for j in range(40)) for i in range(5)]
    doc = "# T\n## Long\n" + "\n\n".join(paragraphs)
    sections = split_sections(doc, max_tokens=100)
    assert len(sections) > 1
    assert all(estimate_tokens(s.body) <= 100 for s in sections)
    assert sections[0].heading == f"Long (part 1/{len(sections)})"
    # Nothing lost, no paragraph cut in half.
    assert "\n\n".join(s.body for s in sections) == "\n\n".join(paragraphs)


def test_oversize_list_split_on_bullets():
    bullets = [f"- item {i} " + " ".join(["word"] * 30) for i in range(6)]
    doc = "# T\n## List\n" + "\n".join(bullets)
    sections = split_sections(doc, max_tokens=80)
    assert len(sections) > 1
    rejoined = "\n\n".join(s.body for s in sections).split("\n\n")
    assert rejoined == bullets  # every bullet whole, in order


def test_oversize_table_is_not_split():
    rows = "\n".join(f"| r{i} | " + " ".join(["x"] * 20) + " |" for i in range(10))
    doc = f"# T\n## Table\n| a | b |\n|---|---|\n{rows}"
    sections = split_sections(doc, max_tokens=50)
    assert len(sections) == 1
    assert sections[0].body.count("\n") == 11


def test_embedding_text_prefixes_title_and_section():
    chunk = Chunk(
        chunk_id="x::00",
        doc_id="x",
        title="Battery Incentive",
        section="Eligibility",
        text="Body.",
        primary="incentive_rebate",
        secondary=[],
        source_path="docs/x.md",
        content_hash="h",
        ingested_at="t",
    )
    assert chunk.embedding_text == "Battery Incentive > Eligibility\nBody."
