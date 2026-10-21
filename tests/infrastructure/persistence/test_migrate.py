import importlib
import sqlite3
from types import SimpleNamespace

import pytest

from jobcaliber.infrastructure.persistence import SCHEMA_VERSION, SchemaMismatch, Store, migrate, schema_version
from jobcaliber.infrastructure.persistence.store import ensure_schema

SCHEMA = "jobcaliber.infrastructure.persistence.schema_version.SCHEMA_VERSION"


def quote(base: str, version: int) -> sqlite3.Connection:
    conn = sqlite3.connect(base)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    return conn


def test_new_database_is_created_at_the_current_version(tmp_path):
    store = Store(tmp_path / "jobs.db")
    with store.connect() as conn:
        assert schema_version(conn) == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_reopening_keeps_data(tmp_path):
    path = tmp_path / "jobs.db"
    store = Store(path)
    store.upsert_posting(__import__("jobcaliber.core.models", fromlist=["JobPosting"]).JobPosting(
        external_id="x", url="x", title="t", company="c", source="s"))
    store2 = Store(path)
    with store2.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_stale_version_refuses_to_open(tmp_path):
    path = tmp_path / "jobs.db"
    Store(path)
    with quote(path, SCHEMA_VERSION - 1):
        pass
    with pytest.raises(SchemaMismatch, match="Run: jobcaliber db migrate"):
        Store(path)


def test_pre_versioning_database_is_rejected_with_the_remedy(tmp_path):
    path = tmp_path / "legacy.db"
    Store(path)
    with quote(path, 0):
        pass
    with pytest.raises(SchemaMismatch, match="before schema versioning"):
        Store(path)


def test_database_from_a_newer_code_is_rejected(tmp_path):
    path = tmp_path / "jobs.db"
    Store(path)
    with quote(path, SCHEMA_VERSION + 1):
        pass
    with pytest.raises(SchemaMismatch, match="newer version"):
        Store(path)


def test_migrate_applies_pending_steps_and_keeps_data(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    store = Store(path)
    store.upsert_posting(__import__("jobcaliber.core.models", fromlist=["JobPosting"]).JobPosting(
        external_id="x", url="x", title="t", company="c", source="s"))
    with quote(path, SCHEMA_VERSION - 1):
        pass

    def up(conn):
        conn.execute("ALTER TABLE jobs ADD COLUMN extra TEXT")

    fake = SimpleNamespace(VERSION=SCHEMA_VERSION, up=up, __name__="m001_fake")
    module = importlib.import_module("jobcaliber.infrastructure.persistence.migrate")
    monkeypatch.setattr(module, "MIGRATIONS", [fake])

    result = module.migrate(path, out=lambda *_: None)

    assert result.from_version == SCHEMA_VERSION - 1
    assert result.to_version == SCHEMA_VERSION
    assert result.applied == ["m001_fake"]
    assert result.backup is not None and result.backup.exists()
    with store.connect() as conn:
        assert schema_version(conn) == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        columns = [row[1] for row in conn.execute("PRAGMA table_info(jobs)")]
        assert "extra" in columns


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    Store(path)
    with quote(path, SCHEMA_VERSION - 1):
        pass
    fake = SimpleNamespace(VERSION=SCHEMA_VERSION, up=lambda conn: None, __name__="m001_fake")
    module = importlib.import_module("jobcaliber.infrastructure.persistence.migrate")
    monkeypatch.setattr(module, "MIGRATIONS", [fake])

    result = module.migrate(path, dry_run=True, out=lambda *_: None)

    assert result.dry_run is True and result.applied == ["m001_fake"]
    with sqlite3.connect(path) as conn:
        assert schema_version(conn) == SCHEMA_VERSION - 1
    assert not path.with_name(f"{path.name}.bak-v{SCHEMA_VERSION - 1}").exists()


def test_a_failing_migration_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    Store(path)
    with quote(path, SCHEMA_VERSION - 1):
        pass

    def up(conn):
        conn.execute("ALTER TABLE jobs ADD COLUMN extra TEXT")
        raise RuntimeError("boom")

    fake = SimpleNamespace(VERSION=SCHEMA_VERSION, up=up, __name__="m001_bad")
    module = importlib.import_module("jobcaliber.infrastructure.persistence.migrate")
    monkeypatch.setattr(module, "MIGRATIONS", [fake])

    with pytest.raises(RuntimeError, match="migration m001_bad failed"):
        module.migrate(path, out=lambda *_: None)
    with sqlite3.connect(path) as conn:
        assert schema_version(conn) == SCHEMA_VERSION - 1
        assert "extra" not in [row[1] for row in conn.execute("PRAGMA table_info(jobs)")]


def test_migrate_on_an_up_to_date_database_does_nothing(tmp_path):
    path = tmp_path / "jobs.db"
    Store(path)
    result = migrate(path, out=lambda *_: None)
    assert result.applied == [] and result.from_version == SCHEMA_VERSION


def test_migrate_refuses_to_go_down(tmp_path):
    path = tmp_path / "jobs.db"
    Store(path)
    with pytest.raises(RuntimeError, match="cannot migrate down"):
        migrate(path, to=SCHEMA_VERSION - 1, out=lambda *_: None)


def test_empty_database_is_created_by_migrate(tmp_path):
    path = tmp_path / "jobs.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    result = migrate(path, out=lambda *_: None)
    assert result.from_version == result.to_version == SCHEMA_VERSION


def test_migrate_rejects_a_pre_versioning_database(tmp_path):
    path = tmp_path / "legacy.db"
    Store(path)
    with quote(path, 0):
        pass
    with pytest.raises(RuntimeError, match="no migration path"):
        migrate(path, out=lambda *_: None)
