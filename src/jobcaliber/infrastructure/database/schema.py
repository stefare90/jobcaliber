"""The database shape: where schema.sql lives, how it is applied and verified."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from jobcaliber.infrastructure.database.schema_version import SCHEMA_VERSION

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def schema_objects(conn: sqlite3.Connection) -> dict[str, str]:
    """The shape of a database: name -> normalised DDL, ignoring sqlite internals."""
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
    ).fetchall()
    # Identifier quoting is not semantic: SQLite adds it when a table is renamed, so a migrated
    # table would otherwise look different from the same table created by schema.sql.
    return {row["name"]: " ".join(row["sql"].split()).replace('"', "") for row in rows}


def table_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]


class SchemaMismatch(RuntimeError):
    """The database schema is not the one this code expects and must be migrated."""


def ensure_schema(conn: sqlite3.Connection, path: Path) -> None:
    """Create an empty database from schema.sql; never alter an existing one."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if table_count(conn) == 0:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return
    if current == SCHEMA_VERSION:
        return
    if current == 0:
        raise SchemaMismatch(
            f"database at {path} was created before schema versioning (v0) and cannot be "
            f"migrated. Delete it and rerun: rm {path}"
        )
    if current > SCHEMA_VERSION:
        raise SchemaMismatch(
            f"database schema v{current} at {path} was created by a newer version than the "
            f"code (v{SCHEMA_VERSION}); update the code or use another database"
        )
    raise SchemaMismatch(
        f"database schema v{current} at {path}, code expects v{SCHEMA_VERSION}. "
        f"Run: jobcaliber db migrate"
    )


