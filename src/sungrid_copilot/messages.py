"""Fixed user-facing text from `config/messages.yaml`. Code fills placeholders, never writes prose."""

from __future__ import annotations

from pathlib import Path

import yaml


class MessagesError(Exception):
    """The messages file is missing a key or a template cannot be filled."""


class Messages:
    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def load(cls, path: Path) -> Messages:
        try:
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            raise MessagesError(f"Cannot read messages file {path}: {e}") from e
        if not isinstance(data, dict):
            raise MessagesError(f"Messages file {path} must be a mapping.")
        return cls(data)

    def require(self, keys: list[str], *, section: str | None = None) -> None:
        """Fail at startup, not mid-conversation, if a needed string is missing."""
        source = self._data.get(section, {}) if section else self._data
        missing = [k for k in keys if not isinstance(source.get(k), str) or not source[k].strip()]
        if missing:
            where = f"section '{section}'" if section else "top level"
            raise MessagesError(f"messages.yaml is missing {where} keys: {', '.join(missing)}")

    def text(self, key: str, **values: object) -> str:
        template = self._data.get(key)
        if not isinstance(template, str):
            raise MessagesError(f"messages.yaml has no text for '{key}'")
        try:
            return template.format(**values).strip()
        except (KeyError, IndexError, ValueError) as e:
            raise MessagesError(f"Cannot fill messages.yaml '{key}': {e}") from e

    def lookup(self, section: str, key: str) -> str:
        value = (self._data.get(section) or {}).get(key)
        if not isinstance(value, str):
            raise MessagesError(f"messages.yaml has no '{section}.{key}'")
        return value.strip()
