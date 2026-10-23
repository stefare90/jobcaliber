"""When a scheduled run is due. Pure functions: the worker only wires them to the clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _in_zone(now: datetime, tz: ZoneInfo) -> datetime:
    """A naive `now` is a wall clock in the configured zone (tests rely on it)."""
    return now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)


def last_scheduled_time(times: list[str], now: datetime, tz: ZoneInfo) -> datetime | None:
    """The most recent configured moment at or before `now`, in the configured zone."""
    local = _in_zone(now, tz)
    candidates = []
    for raw in times:
        try:
            hour, minute = (int(part) for part in raw.split(":", 1))
        except ValueError:
            continue
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > local:
            candidate -= timedelta(days=1)
        candidates.append(candidate)
    return max(candidates) if candidates else None


def is_due(times: list[str], now: datetime, last_run_at: str | None, tz: ZoneInfo) -> bool:
    """True when a scheduled slot has passed since the last scheduled run.
    """
    due = last_scheduled_time(times, now, tz)
    if due is None:
        return False
    if last_run_at is None:
        return True
    last = datetime.fromisoformat(last_run_at)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last < due.astimezone(timezone.utc)
