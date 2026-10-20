"""Retrieval and eligibility are separate components (checked on the AST, not by text search)."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "sungrid_copilot"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import: resolve against the file's package
                package = path.relative_to(PACKAGE.parent).with_suffix("").parts[:-node.level]
                base = ".".join(package)
                modules.add(f"{base}.{node.module}" if node.module else base)
            elif node.module:
                modules.add(node.module)
    return modules


def _touches(modules: set[str], forbidden: str) -> list[str]:
    return sorted(m for m in modules if m == forbidden or m.startswith(forbidden + "."))


RETRIEVAL_SIDE = [PACKAGE / "retrieval.py", *sorted((PACKAGE / "kb").rglob("*.py"))]
ELIGIBILITY_SIDE = sorted((PACKAGE / "eligibility").rglob("*.py"))


@pytest.mark.parametrize("path", RETRIEVAL_SIDE, ids=lambda p: p.name)
def test_retrieval_never_imports_eligibility(path):
    assert _touches(_imported_modules(path), "sungrid_copilot.eligibility") == []


@pytest.mark.parametrize("path", ELIGIBILITY_SIDE, ids=lambda p: p.name)
def test_eligibility_never_imports_retrieval_or_kb(path):
    modules = _imported_modules(path)
    assert _touches(modules, "sungrid_copilot.retrieval") == []
    assert _touches(modules, "sungrid_copilot.kb") == []


def test_checker_sees_imports():
    modules = _imported_modules(PACKAGE / "agent.py")
    assert _touches(modules, "sungrid_copilot.eligibility")
    assert _touches(modules, "sungrid_copilot.retrieval")
