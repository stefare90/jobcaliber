"""Application settings: notifications, scraping and scheduling."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class TelegramConfig(BaseModel):
    enabled: bool = False
    chat_id: str | None = None
    token_env: str = "TELEGRAM_BOT_TOKEN"
    max_offers: int = 10

    @model_validator(mode="after")
    def _enabled_needs_a_chat(self) -> "TelegramConfig":
        if self.enabled and not (self.chat_id or "").strip():
            raise ValueError("notifications.telegram.enabled requires chat_id")
        return self


class Notifications(BaseModel):
    # Where the links inside a notification point (the web app as the phone sees it).
    base_url: str = "http://127.0.0.1:8765"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class Scraping(BaseModel):
    """How the boards are queried, not what is searched (that lives in `search`)."""

    boards: list[str] = Field(default_factory=lambda: ["linkedin", "indeed"])
    page_size: int = 50
    board_max_results: dict[str, int] = Field(default_factory=lambda: {"linkedin": 300, "indeed": 500})
    # Which Indeed site to query (`country_indeed` in JobSpy); LinkedIn ignores it.
    board_country: str = "italy"

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
    timezone: str
    scrape_times: list[str] = Field(default_factory=list)
    backup_time: str = "03:00"
    max_attempts: int = 3


class Evaluation(BaseModel):
    """Decision rules applied to the model's answers (none of them change the answers)."""

    # The confidence a decision engine reports per answer; below it a posting is never `pass`.
    systemone_min_confidence: float = 0.55

    @field_validator("systemone_min_confidence")
    @classmethod
    def _in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"systemone_min_confidence must be within [0, 1], got {value}")
        return value
