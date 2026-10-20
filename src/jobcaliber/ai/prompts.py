"""Prompt store: load and render per-kind templates from `prompts/<kind>/<name>.<ext>`."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

_PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

# Each prompt kind fixes its file extension and the shape of its content.
KIND_EXTENSIONS = {
    "explainer": ".md",
    "query_expander": ".md",
}
LLM_KINDS = {"explainer", "query_expander"}
DEFAULT_NAME = "default"


class PromptError(RuntimeError):
    pass


def placeholders(text: str) -> set[str]:
    return {match.group(1) for match in _PLACEHOLDER.finditer(text)}


def render(text: str, values: dict[str, Any], strict: bool = False) -> str:
    """Substitute `{{name}}`; with `strict`, an unknown name raises instead of surviving."""
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            if strict:
                raise PromptError(f"unresolved placeholder '{{{{{key}}}}}'; known: {sorted(values)}")
            return match.group(0)
        return str(values[key])
    return _PLACEHOLDER.sub(_sub, text)


def split_front_matter(text: str) -> tuple[dict, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    return meta, match.group(2)


class PromptStore:
    def __init__(self, base_dir: Path, custom: dict[str, str] | None = None):
        self.base_dir = base_dir
        self.custom = custom or {}

    def name_for(self, kind: str) -> str:
        return self.custom.get(kind, DEFAULT_NAME)

    def path_for(self, kind: str) -> Path:
        if kind not in KIND_EXTENSIONS:
            raise PromptError(f"unknown prompt kind '{kind}'; expected one of {sorted(KIND_EXTENSIONS)}")
        name = self.name_for(kind)
        path = self.base_dir / kind / f"{name}{KIND_EXTENSIONS[kind]}"
        if not path.exists():
            raise PromptError(f"prompt file not found: {path}")
        return path

    def load_text(self, kind: str, values: dict[str, Any] | None = None) -> str:
        text = self.path_for(kind).read_text(encoding="utf-8")
        return render(text, values or {})

    def load_json(self, kind: str, values: dict[str, Any] | None = None) -> dict:
        return json.loads(self.load_text(kind, values))

    def load_llm(self, kind: str) -> tuple[str, str]:
        """Return the raw (system, user) templates from an LLM prompt's front matter + body."""
        if kind not in LLM_KINDS:
            raise PromptError(f"'{kind}' is not an LLM prompt kind; expected one of {sorted(LLM_KINDS)}")
        meta, body = split_front_matter(self.path_for(kind).read_text(encoding="utf-8"))
        return str(meta.get("system", "")).strip(), body.strip()
