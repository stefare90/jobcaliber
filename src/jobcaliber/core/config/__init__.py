"""Typed configuration. Pure models only: reading a file is I/O and lives in infrastructure."""
from __future__ import annotations

from jobcaliber.core.config.ai import (
    KIND_APIS,
    ROLE_KINDS,
    AIConfig,
    AIEngine,
    ModelHost,
    RetryPolicy,
    WakeOnLan,
)
from jobcaliber.core.config.app import AppConfig
from jobcaliber.core.config.criteria import (
    BOOLEAN_OPTIONS,
    Criterion,
    GateAccept,
    GateMinScore,
    Question,
    validate_criteria,
)
from jobcaliber.core.config.search import Search, validate_search
from jobcaliber.core.config.settings import (
    Evaluation,
    Notifications,
    Schedule,
    Scraping,
    TelegramConfig,
)

__all__ = [
    "BOOLEAN_OPTIONS",
    "KIND_APIS",
    "ROLE_KINDS",
    "AIConfig",
    "AIEngine",
    "ModelHost",
    "AppConfig",
    "Criterion",
    "Evaluation",
    "GateAccept",
    "GateMinScore",
    "Notifications",
    "Question",
    "RetryPolicy",
    "WakeOnLan",
    "Schedule",
    "Scraping",
    "Search",
    "TelegramConfig",
    "validate_criteria",
    "validate_search",
]
