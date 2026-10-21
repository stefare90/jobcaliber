"""runs becomes the run queue: `requested` status and an `attempt` counter.

SQLite cannot alter a CHECK constraint, so the table is rebuilt. The order matters: create the
new table under a temporary name, copy, drop the old one, rename. Renaming the *old* table first
would make SQLite rewrite every foreign key that points to it (evaluations.run_id), leaving the
schema different from schema.sql.
"""
from __future__ import annotations

import sqlite3

VERSION = 3

CREATE = """
CREATE TABLE runs_new (
  id          INTEGER PRIMARY KEY,
  started_at  TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT,
  trigger     TEXT NOT NULL DEFAULT 'schedule' CHECK (trigger IN ('schedule', 'manual', 'cli')),
  config_v    INTEGER,
  engine      TEXT,
  fetched     INTEGER NOT NULL DEFAULT 0,
  usable      INTEGER NOT NULL DEFAULT 0,
  new         INTEGER NOT NULL DEFAULT 0,
  scored      INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER,
  status      TEXT NOT NULL DEFAULT 'running'
              CHECK (status IN ('requested', 'running', 'ok', 'failed')),
  attempt     INTEGER NOT NULL DEFAULT 1,
  error       TEXT
)
"""

COLUMNS = (
    "id, started_at, finished_at, trigger, config_v, engine, fetched, usable, new, scored, "
    "duration_ms, status, error"
)


def up(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE)
    conn.execute(f"INSERT INTO runs_new ({COLUMNS}) SELECT {COLUMNS} FROM runs")
    conn.execute("DROP TABLE runs")
    conn.execute("ALTER TABLE runs_new RENAME TO runs")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, id)")
