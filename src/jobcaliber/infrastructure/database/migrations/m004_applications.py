"""`feedback` (a verdict on one evaluation) becomes `applications` (a state on the posting).

The old rows are not thrown away: a `good` verdict becomes `planned`, a `bad` one `skipped`, with
the original timestamp preserved and the provenance recorded in `source`.
"""
from __future__ import annotations

import sqlite3

VERSION = 4

CREATE = """
CREATE TABLE applications (
  job_id     INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  state      TEXT NOT NULL CHECK (state IN ('applied', 'planned', 'skipped')),
  source     TEXT NOT NULL DEFAULT 'ui',
  note       TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

MIGRATE = """
INSERT INTO applications (job_id, state, source, created_at, updated_at)
SELECT e.job_id,
       CASE f.verdict WHEN 'good' THEN 'planned' ELSE 'skipped' END,
       'feedback:' || f.verdict,
       f.created_at,
       f.created_at
FROM feedback f
JOIN evaluations e ON e.id = f.evaluation_id
WHERE NOT EXISTS (
  SELECT 1 FROM feedback f2 JOIN evaluations e2 ON e2.id = f2.evaluation_id
  WHERE e2.job_id = e.job_id AND f2.created_at > f.created_at
)
"""


def up(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE)
    conn.execute(MIGRATE)
    conn.execute("DROP TABLE feedback")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_state ON applications(state)")
