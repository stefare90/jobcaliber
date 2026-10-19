"""Domain models and data structures for jobcaliber."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GateDecision(str, Enum):
    PASS = "pass"
    DROP = "drop"
    REVIEW = "review"


class LocationBucket(str, Enum):
    PRIMARY = "primary"
    REMOTE = "remote"
    HYBRID = "hybrid"
    ELSEWHERE = "elsewhere"
    UNKNOWN = "unknown"


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
    errors: list[str] = field(default_factory=list)


@dataclass
class SystemOneResult:
    core_score: float  # 0.0 - 1.0
    tools_score: float  # 0.0 - 1.0
    contract_score: float  # 0.0 - 1.0
    pay_score: float  # 0.0 - 1.0
    pay_missing: bool
    location_bucket: LocationBucket
    confidence: float  # 0.0 - 1.0
    summary_reason: str = ""


@dataclass
class EvaluationResult:
    decision: GateDecision
    score_total: float  # 0.0 - 100.0
    confidence: float  # 0.0 - 1.0
    sub_scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
