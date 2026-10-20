"""Project criteria into the `/v1/systemone` question payload (deterministic, no LLM).

The wire schema is strict: a question carries only `type`, `instructions` and `criteria`.
The `missing` marker is ours, not the wire's, so it stays in the config. `{{search.*}}`
placeholders are resolved here, with `strict=True`, so a stale criterion fails at startup.
"""
from __future__ import annotations

from typing import Any

from jobcaliber.ai.prompts import render
from jobcaliber.config import Criterion


def build_systemone_questions(criteria: dict[str, Criterion],
                              values: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    values = values or {}
    questions: dict[str, dict[str, Any]] = {}
    for key, criterion in criteria.items():
        question = criterion.question
        if question.type == "score":
            criteria_payload: Any = [render(level, values, strict=True) for level in question.levels]
        else:
            criteria_payload = {opt: render(text, values, strict=True)
                                for opt, text in question.options.items()}
        questions[key] = {
            "type": question.type,
            "instructions": render(question.instructions, values, strict=True),
            "criteria": criteria_payload,
        }
    return questions
