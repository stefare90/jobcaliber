"""Project criteria into the `/v1/systemone` question payload (deterministic, no LLM).

The wire schema is strict: a question carries only `type`, `instructions` and `criteria`.
The `missing` marker is ours, not the wire's, so it stays in the config.
"""
from __future__ import annotations

from typing import Any

from jobcaliber.config import Criterion


def build_systemone_questions(criteria: dict[str, Criterion]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for key, criterion in criteria.items():
        question = criterion.question
        criteria_payload: Any = list(question.levels) if question.type == "score" else dict(question.options)
        questions[key] = {
            "type": question.type,
            "instructions": question.instructions,
            "criteria": criteria_payload,
        }
    return questions
