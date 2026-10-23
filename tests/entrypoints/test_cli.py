"""The CLI and the web must agree: both render stored UTC in the configured zone."""
from argparse import Namespace
from pathlib import Path
from zoneinfo import ZoneInfo

from jobcaliber.core.formatting import local_time
from jobcaliber.entrypoints.cli import cmd_status
from jobcaliber.infrastructure.config_loader import load_config
from jobcaliber.infrastructure.database import Store

ROOT = Path(__file__).resolve().parents[2]


def test_status_prints_local_time_not_utc(tmp_path, capsys):
    config_path, config = load_config(ROOT)
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    (root / "profile.yaml").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "settings.yaml").write_text(
        (ROOT / "settings.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    db_path = Path(config.db_path)
    store = Store(db_path if db_path.is_absolute() else root / db_path)
    run_id = store.start_run(1, "rizzo", "manual")
    with store.connect() as conn:
        conn.execute("UPDATE runs SET started_at = '2026-10-23 08:00:00', status = 'ok', "
                     "duration_ms = 4200 WHERE id = ?", (run_id,))

    assert cmd_status(Namespace(root=str(root))) == 0
    output = capsys.readouterr().out
    assert "2026-10-23 10:00" in output          # Europe/Rome, CEST
    assert "2026-10-23 08:00" not in output       # the raw UTC value must not leak
    assert "4.2s" in output


def test_the_cli_uses_the_configured_zone():
    _, config = load_config(ROOT)
    assert local_time("2026-10-23 08:00:00", ZoneInfo(config.schedule.timezone)) == "2026-10-23 10:00"
