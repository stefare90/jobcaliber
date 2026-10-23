"""Store: the persistence API used by the pipeline and the web app."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from jobcaliber.core.domain import EvaluationResult, JobPosting, ScoringResult
from jobcaliber.infrastructure.database.schema import ensure_schema


@dataclass
class RunStats:
    fetched: int = 0
    usable: int = 0
    new: int = 0
    scored: int = 0
    status: str = "ok"
    error: str | None = None


@dataclass
class JobRow:
    id: int
    evaluation_id: int
    external_id: str
    title: str
    company: str
    source: str
    location_raw: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    posted_at: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    notified_at: str | None = None
    run_started_at: str | None = None
    decision: str | None = None
    score_total: float | None = None
    confidence: float | None = None
    dropped_by: str | None = None
    answers: dict[str, float | str | None] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def _content_sha(yaml_text: str) -> str:
    return hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()[:16]


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            ensure_schema(conn, self.path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # --- config ---------------------------------------------------------

    def config_version(self, yaml_text: str) -> tuple[int, str]:
        """Return (v, sha); a new version is created only when the content is new."""
        sha = _content_sha(yaml_text)
        with self.connect() as conn:
            row = conn.execute("SELECT v FROM config_versions WHERE sha = ?", (sha,)).fetchone()
            if row:
                return row["v"], sha
            conn.execute("INSERT INTO config_versions (yaml, sha) VALUES (?, ?)", (yaml_text, sha))
            row = conn.execute("SELECT v FROM config_versions WHERE sha = ?", (sha,)).fetchone()
            return row["v"], sha

    def config_yaml(self, v: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT yaml FROM config_versions WHERE v = ?", (v,)).fetchone()
            return row["yaml"] if row else None

    # --- runs -----------------------------------------------------------

    def start_run(self, config_v: int, engine: str, trigger: str = "schedule") -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (config_v, engine, trigger) VALUES (?, ?, ?)",
                (config_v, engine, trigger),
            )
            return int(cur.lastrowid)

    def request_run(self, trigger: str = "manual") -> int:
        """Queue a run: the worker claims it. This is how the web asks for a run."""
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO runs (trigger, status) VALUES (?, 'requested')", (trigger,))
            return int(cur.lastrowid)

    def claim_run(self, config_v: int, engine: str) -> int | None:
        """Atomically turn the oldest request into a running run; None when the queue is empty."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM runs WHERE status = 'requested' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            updated = conn.execute(
                "UPDATE runs SET status = 'running', started_at = datetime('now'), "
                "config_v = ?, engine = ? WHERE id = ? AND status = 'requested'",
                (config_v, engine, row["id"]),
            ).rowcount
            return int(row["id"]) if updated else None

    def requeue(self, run_id: int, max_attempts: int) -> bool:
        """Re-queue a failed run while attempts remain. False when it is exhausted."""
        with self.connect() as conn:
            row = conn.execute("SELECT attempt FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or row["attempt"] >= max_attempts:
                return False
            conn.execute(
                "UPDATE runs SET status = 'requested', attempt = attempt + 1, error = NULL, "
                "finished_at = NULL WHERE id = ?",
                (run_id,),
            )
            return True

    def finish_run(self, run_id: int, stats: RunStats, duration_ms: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = datetime('now'), fetched = ?, usable = ?, new = ?, "
                "scored = ?, duration_ms = ?, status = ?, error = ? WHERE id = ?",
                (stats.fetched, stats.usable, stats.new, stats.scored, duration_ms,
                 stats.status, stats.error, run_id),
            )

    def fail_stale_runs(self) -> int:
        """Mark runs left in 'running' by a killed process as failed."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE runs SET status = 'failed', error = COALESCE(error, 'process died'), "
                "finished_at = COALESCE(finished_at, datetime('now')) WHERE status = 'running'"
            )
            return cur.rowcount

    def run(self, run_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def last_completed_run(self) -> dict | None:
        """The last run that actually produced evaluations (not a request, not a failure)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE status = 'ok' AND scored > 0 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def last_scheduled_run(self) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE trigger = 'schedule' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def last_run(self) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    # --- postings -------------------------------------------------------

    def upsert_posting(self, posting: JobPosting) -> tuple[int, bool]:
        """Insert or refresh one posting. Returns (job_id, is_new)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE external_id = ?", (posting.external_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE jobs SET last_seen_at = datetime('now'), description = COALESCE(?, description), "
                    "salary_min = COALESCE(?, salary_min), salary_max = COALESCE(?, salary_max), "
                    "location_raw = COALESCE(?, location_raw) WHERE id = ?",
                    (posting.description, posting.salary_min, posting.salary_max,
                     posting.location_raw, row["id"]),
                )
                return int(row["id"]), False
            cur = conn.execute(
                "INSERT INTO jobs (external_id, title, company, source, query_term, query_location, "
                "query_remote, location_raw, description, salary_min, salary_max, posted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (posting.external_id, posting.title, posting.company, posting.source,
                 posting.query_term, posting.query_location, int(posting.query_remote),
                 posting.location_raw, posting.description, posting.salary_min,
                 posting.salary_max, posting.posted_at),
            )
            return int(cur.lastrowid), True

    def pending(self, config_v: int, engine: str) -> list[JobPosting]:
        """Postings with no evaluation under this config and engine."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT j.* FROM jobs j WHERE NOT EXISTS ("
                "  SELECT 1 FROM evaluations e WHERE e.job_id = j.id AND e.config_v = ? AND e.engine = ?"
                ") ORDER BY j.id",
                (config_v, engine),
            ).fetchall()
        return [self._to_posting(row) for row in rows]

    @staticmethod
    def _to_posting(row: sqlite3.Row) -> JobPosting:
        return JobPosting(
            external_id=row["external_id"],
            url=row["external_id"],
            title=row["title"],
            company=row["company"],
            source=row["source"],
            location_raw=row["location_raw"],
            description=row["description"],
            salary_min=row["salary_min"],
            salary_max=row["salary_max"],
            posted_at=row["posted_at"],
            query_term=row["query_term"],
            query_location=row["query_location"],
            query_remote=bool(row["query_remote"]),
        )

    # --- evaluations ----------------------------------------------------

    def save_evaluation(self, job_id: int, run_id: int | None, config_v: int, engine: str,
                        result: ScoringResult, evaluation: EvaluationResult) -> int:
        """Store one judgement. Returns the id of the stored (or already existing) evaluation."""
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM evaluations WHERE job_id = ? AND config_v = ? AND engine = ?",
                (job_id, config_v, engine),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cur = conn.execute(
                "INSERT INTO evaluations (job_id, run_id, config_v, engine, decision, score_total, "
                "confidence, dropped_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, run_id, config_v, engine, evaluation.decision.value,
                 evaluation.score_total, evaluation.confidence, evaluation.dropped_by),
            )
            evaluation_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO evaluation_answers (evaluation_id, criterion, value, option, missing) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        evaluation_id,
                        criterion,
                        value if isinstance(value, float) else None,
                        value if isinstance(value, str) else None,
                        int(criterion in result.missing),
                    )
                    for criterion, value in result.answers.items()
                ],
            )
            return evaluation_id

    def evaluation(self, evaluation_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()
            if not row:
                return None
            answers = conn.execute(
                "SELECT criterion, value, option, missing FROM evaluation_answers WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchall()
        data = dict(row)
        data["answers"] = {
            a["criterion"]: (a["option"] if a["option"] is not None else a["value"]) for a in answers
        }
        data["missing"] = [a["criterion"] for a in answers if a["missing"]]
        return data

    # --- feedback -------------------------------------------------------

    def save_feedback(self, evaluation_id: int, verdict: str, note: str | None = None) -> None:
        if verdict not in ("good", "bad"):
            raise ValueError(f"verdict must be 'good' or 'bad', got {verdict!r}")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO feedback (evaluation_id, verdict) VALUES (?, ?) "
                "ON CONFLICT(evaluation_id) DO UPDATE SET verdict = excluded.verdict, "
                "created_at = datetime('now')",
                (evaluation_id, verdict),
            )

    def feedback(self, evaluation_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT verdict FROM feedback WHERE evaluation_id = ?", (evaluation_id,)
            ).fetchone()
            return row["verdict"] if row else None

    # --- notification ---------------------------------------------------

    def new_notifiable(self, limit: int | None = None) -> list[JobRow]:
        """Latest evaluation is pass/review and the posting was never notified."""
        query = (
            "SELECT j.*, e.id AS evaluation_id, e.decision, e.score_total, e.confidence, "
            "e.dropped_by, r.started_at AS run_started_at "
            "FROM jobs j JOIN evaluations e ON e.id = ("
            "  SELECT MAX(id) FROM evaluations e2 WHERE e2.job_id = j.id"
            ") LEFT JOIN runs r ON r.id = e.run_id "
            "WHERE j.notified_at IS NULL AND e.decision IN ('pass','review') "
            "ORDER BY e.score_total DESC"
        )
        if limit:
            query += f" LIMIT {int(limit)}"
        with self.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._to_job_row(row) for row in rows]

    def mark_notified(self, job_ids: list[int]) -> None:
        if not job_ids:
            return
        with self.connect() as conn:
            conn.executemany(
                "UPDATE jobs SET notified_at = datetime('now') WHERE id = ? AND notified_at IS NULL",
                [(job_id,) for job_id in job_ids],
            )

    # --- listing --------------------------------------------------------

    def jobs(self, *, decisions: list[str] | None = None, source: str | None = None,
             text: str | None = None, location: str | None = None,
             criterion: str | None = None, op: str | None = None,
             value: float | None = None, option: str | None = None,
             exclude_missing: bool = False, run_id: int | None = None,
             sort: str = "score_total", direction: str = "desc",
             limit: int = 50, offset: int = 0) -> list[JobRow]:
        """Rows for the web table: the latest evaluation per job, filtered and ordered."""
        where, params = self._where(decisions, source, text, location, criterion, op, value,
                                    option, exclude_missing, run_id)
        order, join, join_params = self._order(sort, direction)
        limit = max(1, min(int(limit), 500))
        query = (
            "SELECT j.*, e.id AS evaluation_id, e.decision, e.score_total, e.confidence, "
            "e.dropped_by, r.started_at AS run_started_at "
            "FROM jobs j JOIN evaluations e ON e.id = "
            "(SELECT MAX(id) FROM evaluations e2 WHERE e2.job_id = j.id) "
            "LEFT JOIN runs r ON r.id = e.run_id "
            f"{join} {where} ORDER BY {order} LIMIT ? OFFSET ?"
        )
        with self.connect() as conn:
            rows = conn.execute(
                query, (*join_params, *params, limit, max(0, int(offset)))
            ).fetchall()
        return [self._to_job_row(row) for row in rows]

    def count_jobs(self, *, decisions: list[str] | None = None, source: str | None = None,
                   text: str | None = None, location: str | None = None,
             criterion: str | None = None, op: str | None = None,
                   value: float | None = None, option: str | None = None,
                   exclude_missing: bool = False, run_id: int | None = None) -> int:
        where, params = self._where(decisions, source, text, location, criterion, op, value,
                                    option, exclude_missing, run_id)
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM jobs j JOIN evaluations e ON e.id = "
                "(SELECT MAX(id) FROM evaluations e2 WHERE e2.job_id = j.id) "
                f"{where}",
                params,
            ).fetchone()[0]

    @staticmethod
    def _where(decisions, source, text, location, criterion, op, value, option, exclude_missing,
               run_id):
        conditions: list[str] = []
        params: list[object] = []
        if decisions:
            conditions.append(f"e.decision IN ({','.join('?' * len(decisions))})")
            params.extend(decisions)
        if source:
            conditions.append("j.source = ?")
            params.append(source)
        if text:
            conditions.append("(j.title LIKE ? OR j.company LIKE ?)")
            params.extend([f"%{text}%", f"%{text}%"])
        if location:
            conditions.append("j.location_raw LIKE ?")
            params.append(f"%{location}%")
        if run_id is not None:
            conditions.append("e.run_id = ?")
            params.append(run_id)
        if exclude_missing:
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM evaluation_answers a "
                "WHERE a.evaluation_id = e.id AND a.missing = 1"
                + (" AND a.criterion = ?" if criterion else "") + ")"
            )
            if criterion:
                params.append(criterion)
        if criterion:
            answer = "EXISTS (SELECT 1 FROM evaluation_answers a WHERE a.evaluation_id = e.id AND a.criterion = ?"
            params.append(criterion)
            if option is not None:
                answer += " AND a.option = ?"
                params.append(option)
            elif op and isinstance(value, float):
                operator = {"lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "="}.get(op)
                if operator is None:
                    raise ValueError(f"unknown comparison operator {op!r}")
                answer += f" AND a.value {operator} ?"
                params.append(value)
            conditions.append(answer + ")")
        return ("WHERE " + " AND ".join(conditions)) if conditions else "", params

    @staticmethod
    def _order(sort: str, direction: str) -> tuple[str, str, tuple]:
        """Order clause plus an optional join: criteria are sorted through their answer row."""
        allowed = {
            "score_total": "e.score_total", "confidence": "e.confidence", "decision": "e.decision",
            "run_started_at": "r.started_at",
            "title": "j.title", "company": "j.company", "source": "j.source",
            "first_seen_at": "j.first_seen_at", "last_seen_at": "j.last_seen_at",
        }
        way = "DESC" if direction.lower() == "desc" else "ASC"
        if sort in allowed:
            return f"{allowed[sort]} {way}, j.id DESC", "", ()
        if sort.startswith("crit:"):
            criterion = sort[len("crit:"):]
            if not criterion.isidentifier():
                raise ValueError(f"cannot sort by criterion {criterion!r}")
            return (
                f"sa.value {way} NULLS LAST, sa.option {way}, j.id DESC",
                "LEFT JOIN evaluation_answers sa ON sa.evaluation_id = e.id AND sa.criterion = ?",
                (criterion,),
            )
        raise ValueError(f"cannot sort by {sort!r}; allowed: {sorted(allowed)} or crit:<name>")

    def job(self, job_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def answers_for(self, evaluation_ids: list[int]) -> dict[int, dict[str, float | str | None]]:
        if not evaluation_ids:
            return {}
        placeholders = ",".join("?" * len(evaluation_ids))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT evaluation_id, criterion, value, option, missing FROM evaluation_answers "
                f"WHERE evaluation_id IN ({placeholders})",
                evaluation_ids,
            ).fetchall()
        answers: dict[int, dict[str, float | str | None]] = {}
        for row in rows:
            value = row["option"] if row["option"] is not None else row["value"]
            answers.setdefault(row["evaluation_id"], {})[row["criterion"]] = value
        return answers

    def missing_for(self, evaluation_ids: list[int]) -> dict[int, set[str]]:
        if not evaluation_ids:
            return {}
        placeholders = ",".join("?" * len(evaluation_ids))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT evaluation_id, criterion FROM evaluation_answers "
                f"WHERE evaluation_id IN ({placeholders}) AND missing = 1",
                evaluation_ids,
            ).fetchall()
        missing: dict[int, set[str]] = {}
        for row in rows:
            missing.setdefault(row["evaluation_id"], set()).add(row["criterion"])
        return missing

    def latest_evaluation(self, job_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM evaluations WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def feedback_for(self, evaluation_ids: list[int]) -> dict[int, str]:
        if not evaluation_ids:
            return {}
        placeholders = ",".join("?" * len(evaluation_ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT evaluation_id, verdict FROM feedback WHERE evaluation_id IN ({placeholders})",
                evaluation_ids,
            ).fetchall()
        return {row["evaluation_id"]: row["verdict"] for row in rows}

    def criterion_columns(self) -> list[str]:
        """The dynamic columns of the web table: one per criterion of the current evaluations."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT a.criterion FROM evaluation_answers a "
                "JOIN evaluations e ON e.id = a.evaluation_id "
                "WHERE e.id = (SELECT MAX(id) FROM evaluations e2 WHERE e2.job_id = e.job_id) "
                "ORDER BY a.criterion"
            ).fetchall()
        return [row["criterion"] for row in rows]

    def runs(self, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def pending_requests(self) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM runs WHERE status = 'requested'"
            ).fetchone()[0]

    @staticmethod
    def _to_job_row(row: sqlite3.Row) -> JobRow:
        data = dict(row)
        return JobRow(
            id=data["id"],
            evaluation_id=data["evaluation_id"],
            external_id=data["external_id"],
            title=data["title"],
            company=data["company"],
            source=data["source"],
            location_raw=data["location_raw"],
            salary_min=data["salary_min"],
            salary_max=data["salary_max"],
            posted_at=data["posted_at"],
            first_seen_at=data["first_seen_at"],
            last_seen_at=data["last_seen_at"],
            notified_at=data["notified_at"],
            run_started_at=data["run_started_at"],
            decision=data["decision"],
            score_total=data["score_total"],
            confidence=data["confidence"],
            dropped_by=data["dropped_by"],
        )
