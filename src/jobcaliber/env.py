"""Minimal .env loader: real environment always wins over the file."""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILENAME = ".env"


class EnvFileError(ValueError):
    pass


def parse_env(text: str, source: str = "<env>") -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            raise EnvFileError(f"{source}:{lineno}: expected KEY=VALUE, got {raw.strip()!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = parse_env(path.read_text(encoding="utf-8"), source=str(path))
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


def load_env(root: Path) -> dict[str, str]:
    return load_env_file(root / ENV_FILENAME)
