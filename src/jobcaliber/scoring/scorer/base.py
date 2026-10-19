"""The Scorer interface, its registry, and the shared normalization helpers."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from jobcaliber.ai.client.base import AIError
from jobcaliber.ai.prompts import PromptStore
from jobcaliber.config import Profile
from jobcaliber.models import JobPosting, LocationBucket, SystemOneResult


class Scorer(ABC):
    """Common interface for every scorer, plus the kind->class registry.

    Concrete scorers subclass it and self-register:
        @Scorer.register("decision")
        class SystemOneScorer(Scorer): ...
    Callers only see `Scorer.create(...)` and `score_posting(...)`.
    """

    _registry: ClassVar[dict[str, type["Scorer"]]] = {}

    @abstractmethod
    def score_posting(self, posting: JobPosting) -> SystemOneResult: ...

    @classmethod
    def register(cls, kind: str):
        def _decorator(subclass: type["Scorer"]) -> type["Scorer"]:
            Scorer._registry[kind] = subclass
            return subclass
        return _decorator

    @classmethod
    def create(cls, client: Any, profile: Profile, prompts: PromptStore) -> "Scorer":
        """Build the scorer registered for the client's engine kind."""
        kind = getattr(getattr(client, "engine", None), "kind", None)
        subclass = Scorer._registry.get(kind)
        if subclass is None:
            raise AIError(f"no scorer registered for engine kind '{kind}'; known: {sorted(Scorer._registry)}")
        return subclass(client, profile, prompts)

    @staticmethod
    def question_values(profile: Profile) -> dict[str, str]:
        return {
            "core_skills": ", ".join(f"{k} (lvl {v})" for k, v in profile.skills.core.items()),
            "tools": ", ".join(profile.skills.tools),
            "seniority": profile.seniority,
            "contract_type": profile.contract_type,
            "primary_location": profile.location.primary,
        }

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
    def location_bucket(value: Any) -> LocationBucket:
        try:
            return LocationBucket(str(value).lower())
        except ValueError:
            return LocationBucket.UNKNOWN

    @staticmethod
    def build_result(*, core: Any, tools: Any, contract: Any, pay: Any, pay_missing: bool,
                     location: Any, confidence: Any, reason: str = "") -> SystemOneResult:
        bucket = Scorer.location_bucket(location)
        return SystemOneResult(
            core_score=Scorer.clamp(core),
            tools_score=Scorer.clamp(tools),
            contract_score=Scorer.clamp(contract),
            pay_score=Scorer.clamp(pay),
            pay_missing=bool(pay_missing),
            location_bucket=bucket,
            confidence=Scorer.clamp(confidence),
            summary_reason=reason or f"Location: {bucket.value}, Core: {Scorer.clamp(core):.2f}",
        )

    @staticmethod
    def parse_json_object(text: str) -> dict:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise AIError(f"scorer returned no JSON object: {text[:200]!r}")
        return json.loads(text[start:end + 1])

    @staticmethod
    def missing_level(question: dict) -> int:
        """Index of the pay level that means 'not stated', inferred from the criteria text."""
        for i, criterion in enumerate(question.get("criteria", [])):
            if "not stated" in str(criterion).lower():
                return i
        return 1
