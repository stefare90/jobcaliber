"""Apply pending migrations. Manual by design: a process may create a database, never alter one."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from jobcaliber.infrastructure.persistence.migrations import MIGRATIONS, SCHEMA_VERSION
from jobcaliber.infrastructure.persistence.store import SCHEMA_PATH, ensure_schema, table_count


@dataclass
class MigrationResult:
    path: Path
    from_version: int
    to_version: int
    applied: list[str] = field(default_factory=list)
    dry_run: bool = False
    backup: Path | None = None


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def pending(conn: sqlite3.Connection, to: int | None = None) -> list:
    current = schema_version(conn)
    limit = to if to is not None else SCHEMA_VERSION
    return [module for module in MIGRATIONS if current < module.VERSION <= limit]


def backup(conn: sqlite3.Connection, path: Path) -> Path:
    target = path.with_name(f"{path.name}.bak-v{schema_version(conn)}")
    with sqlite3.connect(target) as destination:
        conn.backup(destination)
    return target


def migrate(path: Path, to: int | None = None, dry_run: bool = False,
            make_backup: bool = True, out=print) -> MigrationResult:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path)
    try:
        if table_count(conn) == 0:
            ensure_schema(conn, path)
            conn.commit()
            version = schema_version(conn)
            out(f"created empty database at v{version}")
            return MigrationResult(path, version, version)

        start = schema_version(conn)
        if start == 0:
            raise RuntimeError(
                f"{path} has tables but no schema version (pre-versioning database): "
                f"there is no migration path. Delete it and rerun: rm {path}"
            )
        target = to if to is not None else SCHEMA_VERSION
        if start > target:
            raise RuntimeError(
                f"database is v{start}, cannot migrate down to v{target} (no down migrations)"
            )
        steps = pending(conn, target)
        result = MigrationResult(path, start, start, [m.__name__ for m in steps], dry_run)
        if not steps:
            out(f"database already at v{start}, nothing to do")
            return result
        if dry_run:
            for module in steps:
                out(f"would apply {module.__name__} -> v{module.VERSION}")
            result.to_version = steps[-1].VERSION
            return result

        if make_backup:
            result.backup = backup(conn, path)
            out(f"backup {result.backup}")

        for module in steps:
            conn.execute("BEGIN")
            try:
                module.up(conn)
                conn.execute(f"PRAGMA user_version = {module.VERSION}")
                conn.commit()
            except Exception as error:
                conn.rollback()
                raise RuntimeError(f"migration {module.__name__} failed: {error}") from error
            result.to_version = module.VERSION
            out(f"applied {module.__name__} -> v{module.VERSION}")

        if schema_version(conn) != target:
            raise RuntimeError(f"stopped at v{schema_version(conn)}, expected v{target}")
        return result
    finally:
        conn.close()
