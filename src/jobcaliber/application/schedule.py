"""When a scheduled run is due. Pure functions: the worker only wires them to the clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def last_scheduled_time(times: list[str], now: datetime) -> datetime | None:
    """The most recent configured moment at or before `now` (yesterday's if needed)."""
    candidates = []
    for raw in times:
        try:
            hour, minute = (int(part) for part in raw.split(":", 1))
        except ValueError:
            continue
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > now:
            candidate -= timedelta(days=1)
        candidates.append(candidate)
    return max(candidates) if candidates else None


def is_due(times: list[str], now: datetime, last_run_at: str | None) -> bool:
    """True when a scheduled slot has passed since the last scheduled run.

    `last_run_at` comes from SQLite, which stores UTC; comparing it raw with a local clock makes
    every run look hours old and re-triggers one per poll.
    """
    due = last_scheduled_time(times, now)
    if due is None:
        return False
    if last_run_at is None:
        return True
    last = datetime.fromisoformat(last_run_at)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    due_utc = due if due.tzinfo else due.astimezone()
    return last < due_utc.astimezone(timezone.utc)
