"""One JSON line per handled message in logs/queries.jsonl (git-ignored).

Privacy by default: the question text, ZIP, income and other slot values are never logged. The text
is recorded as a SHA-256 hash and a length; `logging.include_query_text` adds it for debugging.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class QueryLogger:
    _lock = threading.Lock()  # several agents (e.g. eval workers) may share one file

    def __init__(self, path: Path, *, include_query_text: bool = False):
        self.path = path
        self.include_query_text = include_query_text

    def write(self, query: str, record: dict) -> dict:
        """Append `record` (which must not hold member text or slot values) plus query metadata."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "query_length": len(query),
            **({"query_text": query} if self.include_query_text else {}),
            **record,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
        return entry
