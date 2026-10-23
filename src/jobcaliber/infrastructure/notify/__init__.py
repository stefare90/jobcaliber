"""Outbound notifications (side effects, so infrastructure)."""
from jobcaliber.infrastructure.notify.telegram import TelegramNotifier

__all__ = ["TelegramNotifier"]
