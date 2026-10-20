"""Typed configuration models (Pydantic v2). Loaded from config.yaml / config.example.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from jobcaliber.env import load_env
from jobcaliber.models import LocationBucket

CONFIG_FILENAME = "config.yaml"
EXAMPLE_FILENAME = "config.example.yaml"

# Allowed wire protocols per engine kind.
KIND_APIS = {"decision": {"systemone"}, "llm": {"openai"}}
# Allowed engine kinds per role (a role may have several implementations).
ROLE_KINDS: dict[str, set[str]] = {
    "scorer": {"decision", "llm"},
    "explainer": {"llm"},
    "query_expander": {"llm"},
}


class RetryPolicy(BaseModel):
    """Retry only transient transport failures (429 / 5xx), never a rejecting answer."""

    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0


class AIEngine(BaseModel):
    kind: str
    api: str
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout_s: float = 120.0
    headers: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    throttle_s: float = 0.0

    @model_validator(mode="after")
    def _validate_kind_api(self) -> "AIEngine":
        if self.kind not in KIND_APIS:
            raise ValueError(f"unknown engine kind '{self.kind}'; expected one of {sorted(KIND_APIS)}")
        if self.api not in KIND_APIS[self.kind]:
            raise ValueError(f"api '{self.api}' is not valid for kind '{self.kind}'; expected {sorted(KIND_APIS[self.kind])}")
        if self.options and self.kind != "llm":
            raise ValueError(
                f"engine '{self.model}': 'options' is only valid for kind 'llm'; "
                f"the systemone wire takes a fixed payload (state/model/questions)"
            )
        return self

    def resolve_api_key(self) -> str:
        return os.environ.get(self.api_key_env, "") if self.api_key_env else ""


class AIConfig(BaseModel):
    prompts_dir: str = "prompts"
    engines: dict[str, AIEngine] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)
    custom_prompts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_roles(self) -> "AIConfig":
        for role, engine_name in self.roles.items():
            if role not in ROLE_KINDS:
                raise ValueError(f"unknown role '{role}'; expected one of {sorted(ROLE_KINDS)}")
            if engine_name not in self.engines:
                raise ValueError(f"role '{role}' references unknown engine '{engine_name}'")
            kind = self.engines[engine_name].kind
            if kind not in ROLE_KINDS[role]:
                raise ValueError(f"role '{role}' accepts {sorted(ROLE_KINDS[role])} engines, but '{engine_name}' is '{kind}'")
        return self


class LocationPrefs(BaseModel):
    """Query strings are passed to the boards verbatim: write them the way the board spells them."""

    primary: str
    remote_query: str | None = None
    hybrid_max_km: int = 40

    @model_validator(mode="after")
    def _normalize_remote_query(self) -> "LocationPrefs":
        if self.remote_query is not None:
            self.remote_query = self.remote_query.strip() or None
        return self


class Skills(BaseModel):
    core: dict[str, int] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    titles: list[str]
    seniority: str = "mid"
    contract_type: str = "permanent"
    skills: Skills = Field(default_factory=Skills)
    location: LocationPrefs


class FilterParam(BaseModel):
    mode: str = "weighted"
    weight: float = 0.0


class PayFilter(FilterParam):
    target_annual: float = 40000.0
    min_annual: float = 38000.0
    hard_drop_tolerance: float = 0.05


class LocationFilter(FilterParam):
    mode: str = "hard_gate"
    weight: float = 0.0
    # Sub-scores used only when mode is 'weighted' (location.weight > 0).
    bucket_scores: dict[str, float] = Field(default_factory=lambda: {
        "primary": 1.0, "remote": 1.0, "hybrid": 0.8, "unknown": 0.5, "elsewhere": 0.0,
    })

    @model_validator(mode="after")
    def _validate_bucket_keys(self) -> "LocationFilter":
        expected = {b.value for b in LocationBucket}
        got = set(self.bucket_scores)
        if got != expected:
            raise ValueError(f"bucket_scores keys {sorted(got)} must equal LocationBucket values {sorted(expected)}")
        return self


class ConfidencePenalties(BaseModel):
    location_unknown: float = 0.8
    pay_missing: float = 0.85


class JobFilters(BaseModel):
    core_skills: FilterParam = Field(default_factory=lambda: FilterParam(weight=45))
    tools: FilterParam = Field(default_factory=lambda: FilterParam(weight=20))
    contract: FilterParam = Field(default_factory=lambda: FilterParam(weight=20))
    pay: PayFilter = Field(default_factory=lambda: PayFilter(weight=15))
    location: LocationFilter = Field(default_factory=LocationFilter)
    confidence_penalties: ConfidencePenalties = Field(default_factory=ConfidencePenalties)


class TelegramNotifications(BaseModel):
    enabled: bool = True
    notify_threshold: float = 70.0
    review_threshold: float = 60.0
    min_confidence: float = 0.55
    quiet_hours: str = "22-08"
    digest_time: str = "20:00"


class Notifications(BaseModel):
    telegram: TelegramNotifications = Field(default_factory=TelegramNotifications)


class Scraping(BaseModel):
    boards: list[str] = Field(default_factory=lambda: ["linkedin", "indeed"])
    country: str = "italy"
    hours_old: int | None = None
    page_size: int = 50
    board_max_results: dict[str, int] = Field(default_factory=lambda: {"linkedin": 300, "indeed": 500})
    job_type: str | None = "fulltime"

    @model_validator(mode="after")
    def _validate_board_max_results(self) -> "Scraping":
        unknown = set(self.board_max_results) - set(self.boards)
        if unknown:
            raise ValueError(f"board_max_results names unknown boards {sorted(unknown)}; boards are {sorted(self.boards)}")
        return self

    def max_results(self, board: str) -> int:
        if board in self.board_max_results:
            return self.board_max_results[board]
        return max(self.board_max_results.values(), default=100)


class Schedule(BaseModel):
    scrape_times: list[str] = Field(default_factory=list)
    backup_time: str = "03:00"


class AppConfig(BaseModel):
    version: int = 10
    db_path: str = "./data/jobs.db"
    profile: Profile
    job_filters: JobFilters = Field(default_factory=JobFilters)
    notifications: Notifications = Field(default_factory=Notifications)
    scraping: Scraping = Field(default_factory=Scraping)
    schedule: Schedule = Field(default_factory=Schedule)
    ai: AIConfig = Field(default_factory=AIConfig)


def load_config(root: Path) -> tuple[Path, AppConfig]:
    load_env(root)
    path = root / CONFIG_FILENAME
    if not path.exists():
        path = root / EXAMPLE_FILENAME
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return path, AppConfig.model_validate(raw)
