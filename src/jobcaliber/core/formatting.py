"""Human-facing timestamps: the DB stores UTC, people read wall clock in the configured zone.

Pure presentation helpers with no I/O. They live in `core` (the only layer every other layer may
import) so the web, the CLI and the future notifier format dates the same way.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_FORMAT = "%Y-%m-%d %H:%M"


def local_time(value: str | None, tz: ZoneInfo, fmt: str = DEFAULT_FORMAT) -> str:
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime(fmt)


def duration_text(ms: int | None) -> str:
    return "—" if ms is None else f"{ms / 1000:.1f}s"
