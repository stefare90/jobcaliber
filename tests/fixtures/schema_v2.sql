-- jobcaliber schema v2 (SQLite, WAL). Applied idempotently by Store on every open.
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

-- One row per posting ever seen. `external_id` is the board URL: identity and link in one field.
CREATE TABLE IF NOT EXISTS jobs (
  id            INTEGER PRIMARY KEY,
  external_id   TEXT NOT NULL UNIQUE,
  title         TEXT NOT NULL,
  company       TEXT NOT NULL,
  source        TEXT NOT NULL,
  query_term    TEXT,
  query_location TEXT,
  query_remote  INTEGER NOT NULL DEFAULT 0,
  location_raw  TEXT,
  description   TEXT,
  salary_min    REAL,
  salary_max    REAL,
  posted_at     TEXT,
  first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at  TEXT NOT NULL DEFAULT (datetime('now')),
  notified_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_notify ON jobs(notified_at);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);

-- One row per execution (scheduled, manual or CLI).
CREATE TABLE IF NOT EXISTS runs (
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
  status      TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed')),
  error       TEXT
);

-- Config snapshots, keyed by content: the same file never produces two versions.
CREATE TABLE IF NOT EXISTS config_versions (
  v          INTEGER PRIMARY KEY,
  yaml       TEXT NOT NULL,
  sha        TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per judgement. Re-scoring with the same config_v and engine is a no-op (UNIQUE).
CREATE TABLE IF NOT EXISTS evaluations (
  id          INTEGER PRIMARY KEY,
  job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  run_id      INTEGER REFERENCES runs(id) ON DELETE SET NULL,
  config_v    INTEGER NOT NULL,
  engine      TEXT NOT NULL,
  decision    TEXT NOT NULL CHECK (decision IN ('pass', 'review', 'drop')),
  score_total REAL,
  confidence  REAL,
  dropped_by  TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (job_id, config_v, engine)
);
CREATE INDEX IF NOT EXISTS idx_eval_job ON evaluations(job_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_eval_decision ON evaluations(decision, score_total);

-- Answers normalised: criterion keys are dynamic, so they cannot be columns.
CREATE TABLE IF NOT EXISTS evaluation_answers (
  evaluation_id INTEGER NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
  criterion     TEXT NOT NULL,
  value         REAL,
  option        TEXT,
  missing       INTEGER NOT NULL DEFAULT 0 CHECK (missing IN (0, 1)),
  PRIMARY KEY (evaluation_id, criterion)
);
CREATE INDEX IF NOT EXISTS idx_answers_criterion ON evaluation_answers(criterion, value);

-- The user's verdict on one judgement: good or bad. Updatable, one per evaluation.
CREATE TABLE IF NOT EXISTS feedback (
  id            INTEGER PRIMARY KEY,
  evaluation_id INTEGER NOT NULL UNIQUE REFERENCES evaluations(id) ON DELETE CASCADE,
  verdict       TEXT NOT NULL CHECK (verdict IN ('good', 'bad')),
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
