"""Project criteria into the `/v1/systemone` question payload (deterministic, no LLM)."""
from __future__ import annotations

from typing import Any

from jobcaliber.config import Criterion


def build_systemone_questions(criteria: dict[str, Criterion]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for key, criterion in criteria.items():
        question = criterion.question
        payload: dict[str, Any] = {"type": question.type, "instructions": question.instructions}
        if question.type == "score":
            payload["criteria"] = list(question.levels)
            payload["missing_level"] = question.missing
        else:
            payload["criteria"] = dict(question.options)
            payload["missing_choice"] = question.missing
        questions[key] = payload
    return questions
