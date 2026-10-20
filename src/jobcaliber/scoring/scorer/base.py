"""The Scorer interface, its registry, and the shared normalization helpers."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from jobcaliber.ai.client.base import AIError
from jobcaliber.ai.prompts import PromptStore
from jobcaliber.config import Criterion
from jobcaliber.models import JobPosting, ScoringResult


class Scorer(ABC):
    """Common interface for every scorer, plus the kind->class registry.

    Concrete scorers subclass it and self-register:
        @Scorer.register("decision")
        class SystemOneScorer(Scorer): ...
    Callers only see `Scorer.create(...)` and `score_posting(...)`.
    """

    _registry: ClassVar[dict[str, type["Scorer"]]] = {}

    @abstractmethod
    def score_posting(self, posting: JobPosting) -> ScoringResult: ...

    @classmethod
    def register(cls, kind: str):
        def _decorator(subclass: type["Scorer"]) -> type["Scorer"]:
            Scorer._registry[kind] = subclass
            return subclass
        return _decorator

    @classmethod
    def create(cls, client: Any, criteria: dict[str, Criterion], prompts: PromptStore,
               values: dict[str, str] | None = None) -> "Scorer":
        """Build the scorer registered for the client's engine kind."""
        kind = getattr(getattr(client, "engine", None), "kind", None)
        subclass = Scorer._registry.get(kind)
        if subclass is None:
            raise AIError(f"no scorer registered for engine kind '{kind}'; known: {sorted(Scorer._registry)}")
        return subclass(client, criteria, prompts, values or {})

    @staticmethod
    def build_state(posting: JobPosting) -> str:
        parts = [
            f"Job Title: {posting.title}",
            f"Company: {posting.company}",
            f"Declared Location: {posting.location_raw or 'Not specified'}",
        ]
        if posting.salary_min or posting.salary_max:
            parts.append(f"Salary: {posting.salary_min or ''} - {posting.salary_max or ''}")
        if posting.description:
            parts.append(f"Description:\n{posting.description}")
        return "\n".join(parts)

    @staticmethod
    def clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
        try:
            return min(high, max(low, float(value)))
        except (TypeError, ValueError):
            return low

    @staticmethod
    def build_result(*, answers: dict[str, float | str], missing: set[str] | None = None,
                     confidence: Any = 0.85, reason: str = "") -> ScoringResult:
        return ScoringResult(
            answers={key: (Scorer.clamp(value) if isinstance(value, (int, float)) else str(value))
                     for key, value in answers.items()},
            missing=set(missing or set()),
            confidence=Scorer.clamp(confidence),
            summary_reason=reason,
        )

    @staticmethod
    def parse_json_object(text: str) -> dict:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise AIError(f"scorer returned no JSON object: {text[:200]!r}")
        return json.loads(text[start:end + 1])
