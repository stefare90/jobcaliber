"""Domain models and data structures for jobcaliber."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GateDecision(str, Enum):
    PASS = "pass"
    DROP = "drop"
    REVIEW = "review"


@dataclass
class JobPosting:
    external_id: str
    url: str
    title: str
    company: str
    source: str
    location_raw: str | None = None
    description: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    posted_at: str | None = None
    search_id: str | None = None


@dataclass
class Query:
    keywords: str
    location: str
    role: str
    remote: bool = False


@dataclass
class FetchStats:
    seen: int = 0
    usable: int = 0
    new: int = 0
    captcha_skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ScoringResult:
    """One answer per configured criterion: 0.0-1.0 for a score, an option key for a choice."""

    answers: dict[str, float | str]
    missing: set[str] = field(default_factory=set)
    confidence: float = 0.85
    summary_reason: str = ""


@dataclass
class EvaluationResult:
    decision: GateDecision
    score_total: float  # 0.0 - 100.0
    confidence: float  # 0.0 - 1.0
    sub_scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    dropped_by: str | None = None
