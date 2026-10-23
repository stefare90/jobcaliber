"""AppConfig: the whole configuration, validated as one unit."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jobcaliber.core.config.ai import AIConfig
from jobcaliber.core.config.criteria import Criterion, validate_criteria
from jobcaliber.core.config.search import Search, validate_search
from jobcaliber.core.config.settings import Evaluation, Notifications, Schedule, Scraping


# Bumped when the projection of `criteria` into the model's rubric changes shape: without it,
# stored answers would look valid although they were produced by a different set of questions.
RUBRIC_VERSION = 1


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_path: str = "./data/jobs.db"
    search: Search
    evaluation: Evaluation = Field(default_factory=Evaluation)
    criteria: dict[str, Criterion]
    notifications: Notifications = Field(default_factory=Notifications)
    scraping: Scraping = Field(default_factory=Scraping)
    schedule: Schedule = Field(default_factory=Schedule)
    ai: AIConfig = Field(default_factory=AIConfig)

    @model_validator(mode="after")
    def _validate_schema(self) -> "AppConfig":
        validate_search(self.search)
        validate_criteria(self.criteria)
        return self
