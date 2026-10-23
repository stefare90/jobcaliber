"""Application settings: notifications, scraping and scheduling."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

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
    timezone: str
    scrape_times: list[str] = Field(default_factory=list)
    backup_time: str = "03:00"
    max_attempts: int = 3
