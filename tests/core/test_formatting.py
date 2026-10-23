"""UTC in the database, wall clock in the configured zone on every screen."""
from datetime import datetime
from zoneinfo import ZoneInfo

from jobcaliber.core.formatting import duration_text, local_time

ROME = ZoneInfo("Europe/Rome")


def test_summer_and_winter_use_the_real_zone_not_a_fixed_offset():
    assert local_time("2026-10-23 08:00:00", ROME) == "2026-10-23 10:00"   # CEST, UTC+2
    assert local_time("2026-12-01 08:00:00", ROME) == "2026-12-01 09:00"   # CET, UTC+1


def test_missing_or_unparsable_values_do_not_break_the_page():
    assert local_time(None, ROME) == "—"
    assert local_time("", ROME) == "—"
    assert local_time("not a date", ROME) == "not a date"


def test_an_aware_value_is_converted_too():
    assert local_time(datetime(2026, 10, 23, 8, 0, tzinfo=ZoneInfo("UTC")).isoformat(), ROME) == "2026-10-23 10:00"


def test_duration_text():
    assert duration_text(None) == "—"
    assert duration_text(144423) == "144.4s"
