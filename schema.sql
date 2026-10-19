-- consulente-lavoro-ai schema v1 (SQLite WAL, English-only)
PRAGMA journal_mode=WAL;

-- One row per unique job posting. Norm columns drive dedup; sub-scores explain the total.
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  external_id TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  url_norm TEXT NOT NULL,
  company TEXT NOT NULL,
  company_norm TEXT NOT NULL,
  title TEXT NOT NULL,
  title_norm TEXT NOT NULL,
  source TEXT NOT NULL,
  search_id TEXT,
  posted_at TEXT,
  salary_min INTEGER, salary_max INTEGER, salary_source TEXT DEFAULT 'unknown',
  location_raw TEXT, arrangement TEXT,
  s_core REAL, s_tools REAL, s_pay REAL, s_contract REAL, s_location REAL,
  score_total REAL, confidence REAL,
  reason TEXT,
  notified INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new',
  raw_path TEXT,
  first_run_id INTEGER, last_seen_run_id INTEGER, times_seen INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_score ON jobs(status, score_total);
CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(company_norm, title_norm);

-- One row per scheduled run. No cost columns (free/local engines).
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT DEFAULT (datetime('now')),
  config_v INTEGER,
  source TEXT, found INTEGER DEFAULT 0, new INTEGER DEFAULT 0,
  scored INTEGER DEFAULT 0, notified INTEGER DEFAULT 0,
  duration_ms INTEGER DEFAULT 0,
  errors TEXT, summary TEXT
);

-- Explicit user verdicts only. reason_category is fixed list, reason_text is free natural language.
CREATE TABLE IF NOT EXISTS feedback (
  job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  verdict TEXT NOT NULL,
  reason_category TEXT,
  reason_text TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- Personal config history, never pushed. Active row drives runs.
CREATE TABLE IF NOT EXISTS config_versions (
  v INTEGER PRIMARY KEY,
  yaml TEXT NOT NULL,
  note TEXT,
  active INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
