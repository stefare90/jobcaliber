"""Typed configuration models (Pydantic v2). Loaded from config.yaml / config.example.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from jobcaliber.env import load_env

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


class GateAccept(BaseModel):
    accept: list[str]


class GateMinScore(BaseModel):
    min_score: float


class SearchLocation(BaseModel):
    """A board query location: `query` is sent to the board verbatim."""

    query: str
    remote: bool = False


class Search(BaseModel):
    titles: list[str] = Field(default_factory=list)
    locations: list[SearchLocation] = Field(default_factory=list)


class Question(BaseModel):
    """The scoring question for one criterion; the answer type fixes how it is used."""

    type: Literal["score", "choice"]
    instructions: str
    levels: list[str] = Field(default_factory=list)
    options: dict[str, str] = Field(default_factory=dict)
    missing: int | str


class Criterion(BaseModel):
    """Weighted dimension (`weight > 0`) or hard gate (`gate`), never both."""

    weight: float = 0.0
    gate: bool | GateAccept | GateMinScore | None = None
    question: Question


BOOLEAN_OPTIONS = {"yes", "no", "missing"}


def validate_search(search: Search) -> None:
    if not [t for t in search.titles if t.strip()]:
        raise ValueError("search needs at least one non-empty title")
    if not [loc for loc in search.locations if loc.query.strip()]:
        raise ValueError("search needs at least one non-empty location query")


def _validate_question(key: str, criterion: Criterion) -> None:
    question = criterion.question
    if question.type == "score":
        if len(question.levels) < 2:
            raise ValueError(
                f"criterion '{key}': a score question needs at least 2 levels, got {len(question.levels)}"
            )
        if not isinstance(question.missing, int) or isinstance(question.missing, bool):
            raise ValueError(
                f"criterion '{key}': 'missing' must be a level index for a score question, got {question.missing!r}"
            )
        if not 0 <= question.missing < len(question.levels):
            raise ValueError(
                f"criterion '{key}': 'missing' level index must be within [0, {len(question.levels) - 1}], "
                f"got {question.missing}"
            )
    else:
        if not question.options:
            raise ValueError(f"criterion '{key}': a choice question needs at least one option")
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
        if criterion.question.missing in gate.accept:
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


def validate_criteria(criteria: dict[str, Criterion], penalties: dict[str, float] | None = None) -> None:
    if not criteria:
        raise ValueError("at least one criterion is required")
    for key, criterion in criteria.items():
        has_gate = criterion.gate is not None and criterion.gate is not False
        if criterion.weight > 0 and has_gate:
            raise ValueError(f"criterion '{key}': set either weight > 0 or a gate, not both")
        if criterion.weight <= 0 and not has_gate:
            raise ValueError(f"criterion '{key}': set either weight > 0 or a gate")
        if criterion.weight > 0 and criterion.question.type != "score":
            raise ValueError(
                f"criterion '{key}': a weighted criterion needs a 'score' question, "
                f"got '{criterion.question.type}'"
            )
        _validate_question(key, criterion)
        if has_gate:
            _validate_gate(key, criterion)
    for key, penalty in (penalties or {}).items():
        if key not in criteria:
            raise ValueError(f"penalty for unknown criterion '{key}'; known: {sorted(criteria)}")
        if not 0.0 < penalty <= 1.0:
            raise ValueError(f"criterion '{key}': penalty must be within (0, 1], got {penalty}")


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
    model_config = ConfigDict(extra="forbid")

    version: int = 11
    db_path: str = "./data/jobs.db"
    search: Search
    criteria: dict[str, Criterion]
    penalties: dict[str, float] = Field(default_factory=dict)
    notifications: Notifications = Field(default_factory=Notifications)
    scraping: Scraping = Field(default_factory=Scraping)
    schedule: Schedule = Field(default_factory=Schedule)
    ai: AIConfig = Field(default_factory=AIConfig)

    @model_validator(mode="after")
    def _validate_schema(self) -> "AppConfig":
        validate_search(self.search)
        validate_criteria(self.criteria, self.penalties)
        return self


def load_config(root: Path) -> tuple[Path, AppConfig]:
    load_env(root)
    path = root / CONFIG_FILENAME
    if not path.exists():
        path = root / EXAMPLE_FILENAME
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return path, AppConfig.model_validate(raw)
