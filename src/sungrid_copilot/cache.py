"""Small on-disk JSON cache for LLM results (classifier, slot extraction)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


class JsonCache:
    """One JSON file per key. Writes are atomic, so it is safe to share across threads."""

    def __init__(self, directory: Path):
        self.directory = directory

    @staticmethod
    def key(*parts: str) -> str:
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        try:
            return json.loads((self.directory / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, payload: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.directory / f"{key}.json")
