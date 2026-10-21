"""Typed configuration. Pure models only: reading a file is I/O and lives in infrastructure."""
from __future__ import annotations

from jobcaliber.core.config.ai import KIND_APIS, ROLE_KINDS, AIConfig, AIEngine, RetryPolicy
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
from jobcaliber.core.config.settings import Notifications, Schedule, Scraping, TelegramNotifications

__all__ = [
    "BOOLEAN_OPTIONS",
    "KIND_APIS",
    "ROLE_KINDS",
    "AIConfig",
    "AIEngine",
    "AppConfig",
    "Criterion",
    "GateAccept",
    "GateMinScore",
    "Notifications",
    "Question",
    "RetryPolicy",
    "Schedule",
    "Scraping",
    "Search",
    "TelegramNotifications",
    "validate_criteria",
    "validate_search",
]
