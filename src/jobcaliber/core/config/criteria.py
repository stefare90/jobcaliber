"""Criteria: the scored dimensions and their gates, with validation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from jobcaliber.core.config.search import Search

class GateAccept(BaseModel):
    accept: list[str]


class GateMinScore(BaseModel):
    min_score: float


class Question(BaseModel):
    """The scoring question for one criterion; the answer type fixes how it is used."""

    type: Literal["score", "choice"]
    instructions: str
    levels: list[str] = Field(default_factory=list)
    options: dict[str, str] = Field(default_factory=dict)
    missing: int | str | None = None


class Criterion(BaseModel):
    """Scored dimension (thresholds) or hard gate (`gate`), never both.

    `min_threshold` drops below it; `apply_threshold` marks the PASS band. A missing answer
    is exempt from both: it never drops and it forces REVIEW.
    """

    min_threshold: float | None = None
    apply_threshold: float | None = None
    gate: bool | GateAccept | GateMinScore | None = None
    question: Question


BOOLEAN_OPTIONS = {"yes", "no", "missing"}


def _validate_question(key: str, criterion: Criterion) -> None:
    question = criterion.question
    if question.type == "score":
        if len(question.levels) < 2:
            raise ValueError(
                f"criterion '{key}': a score question needs at least 2 levels, got {len(question.levels)}"
            )
        if question.missing is None:
            return
        if not isinstance(question.missing, int) or isinstance(question.missing, bool):
            raise ValueError(
                f"criterion '{key}': 'missing' must be a level index or null for a score question, "
                f"got {question.missing!r}"
            )
        if not 0 <= question.missing < len(question.levels):
            raise ValueError(
                f"criterion '{key}': 'missing' level index must be within [0, {len(question.levels) - 1}], "
                f"got {question.missing}"
            )
    else:
        if not question.options:
            raise ValueError(f"criterion '{key}': a choice question needs at least one option")
        if question.missing is None:
            return
        if not isinstance(question.missing, str) or question.missing not in question.options:
            raise ValueError(
                f"criterion '{key}': 'missing' must be one of the options {sorted(question.options)}, "
                f"got {question.missing!r}"
            )


def _validate_gate(key: str, criterion: Criterion) -> None:
    gate, options = criterion.gate, criterion.question.options
    if gate is True:
        if criterion.question.type != "choice" or set(options) != BOOLEAN_OPTIONS:
            raise ValueError(
                f"criterion '{key}': a boolean gate needs a 'choice' question with exactly the options "
                f"yes/no/missing, got type '{criterion.question.type}' and options {sorted(options)}"
            )
        return
    if isinstance(gate, GateAccept):
        if criterion.question.type != "choice":
            raise ValueError(
                f"criterion '{key}': gate.accept needs a 'choice' question, got '{criterion.question.type}'"
            )
        if not gate.accept:
            raise ValueError(f"criterion '{key}': gate.accept needs at least one accepted option")
        unknown = set(gate.accept) - set(options)
        if unknown:
            raise ValueError(
                f"criterion '{key}': gate.accept names {sorted(unknown)} which are not options {sorted(options)}"
            )
        if criterion.question.missing is not None and criterion.question.missing in gate.accept:
            raise ValueError(
                f"criterion '{key}': the missing option '{criterion.question.missing}' cannot be accepted "
                f"by a gate (a missing answer must never drop, and never pass either)"
            )
        return
    if isinstance(gate, GateMinScore):
        if criterion.question.type != "score":
            raise ValueError(
                f"criterion '{key}': gate.min_score needs a 'score' question, got '{criterion.question.type}'"
            )
        if not 0.0 <= gate.min_score <= 1.0:
            raise ValueError(f"criterion '{key}': gate.min_score must be within [0, 1], got {gate.min_score}")


def validate_criteria(criteria: dict[str, Criterion]) -> None:
    if not criteria:
        raise ValueError("at least one criterion is required")
    for key, criterion in criteria.items():
        has_gate = criterion.gate is not None and criterion.gate is not False
        scored = criterion.min_threshold is not None or criterion.apply_threshold is not None
        if has_gate and scored:
            raise ValueError(f"criterion '{key}': a gate cannot also carry thresholds")
        if not has_gate and not scored:
            raise ValueError(f"criterion '{key}': set a gate or at least one threshold")
        if not has_gate and criterion.question.type != "score":
            raise ValueError(
                f"criterion '{key}': a scored criterion needs a 'score' question, "
                f"got '{criterion.question.type}'"
            )
        for name in ("min_threshold", "apply_threshold"):
            value = getattr(criterion, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"criterion '{key}': {name} must be within [0, 1], got {value}")
        if (criterion.min_threshold is not None and criterion.apply_threshold is not None
                and criterion.min_threshold > criterion.apply_threshold):
            raise ValueError(
                f"criterion '{key}': min_threshold {criterion.min_threshold} is above "
                f"apply_threshold {criterion.apply_threshold}"
            )
        _validate_question(key, criterion)
        if has_gate:
            _validate_gate(key, criterion)
    if not any(c.gate is None or c.gate is False for c in criteria.values()):
        raise ValueError("at least one scored criterion is required")
