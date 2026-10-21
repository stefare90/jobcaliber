"""CLI: `python -m jobcaliber run|status`. The web app and the scheduler call the same code."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from jobcaliber.application.runner import run_once
from jobcaliber.bootstrap import build_context
from jobcaliber.infrastructure.config_loader import load_config
from jobcaliber.infrastructure.database import SCHEMA_VERSION, migrate, schema_version
from jobcaliber.infrastructure.database import SCHEMA_PATH, schema_objects, table_count

DEFAULT_ROOT = Path(__file__).resolve().parents[3]


def cmd_run(args: argparse.Namespace) -> int:
    ctx = build_context(Path(args.root), engine=args.engine)
    outcome = run_once(
        ctx, limit=args.limit, max_queries=args.max_queries,
        trigger=args.trigger, dry_run=args.dry_run,
    )
    print(
        f"\n{'(dry run) ' if outcome.dry_run else ''}run {outcome.run_id} · config_v {outcome.config_v} "
        f"· engine {outcome.engine} · {outcome.duration_ms} ms"
    )
    print(
        f"fetched {outcome.fetched} · new {outcome.new} · scored {outcome.scored} · "
        + " · ".join(f"{k} {v}" for k, v in sorted(outcome.decisions.items()))
    )
    if outcome.failed:
        print(f"FAILED: {outcome.error}", file=sys.stderr)
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ctx = build_context(Path(args.root))
    last = ctx.store.last_run()
    if not last:
        print("no runs yet")
        return 0
    print(
        f"run {last['id']} · {last['started_at']} · {last['status']} · trigger {last['trigger']} "
        f"· engine {last['engine']} · config_v {last['config_v']}"
    )
    print(
        f"fetched {last['fetched']} · usable {last['usable']} · new {last['new']} "
        f"· scored {last['scored']} · {last['duration_ms']} ms"
    )
    if last["error"]:
        print(f"error: {last['error']}")
    notifiable = ctx.store.new_notifiable()
    print(f"notifiable (pass/review, never notified): {len(notifiable)}")
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    ctx = build_context(Path(args.root))
    rows = ctx.store.jobs(decision=args.decision, source=args.source, text=args.text, limit=args.limit)
    for row in rows:
        print(f"{row.decision or '-':6} {row.score_total or 0:5.1f} {row.title[:58]:60} {row.company[:24]}")
    print(f"\n{len(rows)} rows")
    return 0


def _db_path(args: argparse.Namespace) -> Path:
    """Resolve the database path without opening it: `db` commands must work on a stale file."""
    root = Path(args.root).resolve()
    _, config = load_config(root)
    path = Path(config.db_path)
    return path if path.is_absolute() else root / path


def cmd_db(args: argparse.Namespace) -> int:
    path = _db_path(args)
    if args.db_command == "version":
        with _connect(path) as conn:
            current = schema_version(conn)
            empty = table_count(conn) == 0
        if empty:
            print(f"{path}: new database (will be created at v{SCHEMA_VERSION} on first use)")
            return 0
        print(f"{path}: schema v{current} (code expects v{SCHEMA_VERSION})")
        return 0 if current == SCHEMA_VERSION else 1
    if args.db_command == "migrate":
        result = migrate(path, to=args.to, dry_run=args.dry_run, make_backup=not args.no_backup)
        print(f"v{result.from_version} -> v{result.to_version}")
        return 0
    if args.db_command == "check":
        with _connect(path) as conn:
            if table_count(conn) == 0:
                print(f"{path}: new database (will be created at v{SCHEMA_VERSION} on first use)")
                return 0
            actual = schema_objects(conn)
        reference_conn = sqlite3.connect(":memory:")
        reference_conn.row_factory = sqlite3.Row
        reference_conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        expected = schema_objects(reference_conn)
        reference_conn.close()
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(name for name in set(expected) & set(actual) if expected[name] != actual[name])
        if not (missing or extra or changed):
            print(f"{path}: schema matches schema.sql")
            return 0
        for name in missing:
            print(f"missing: {name}")
        for name in extra:
            print(f"extra:   {name}")
        for name in changed:
            print(f"differs: {name}")
        return 1
    if args.db_command == "backup":
        target = Path(args.to) if args.to else path.with_name(f"{path.name}.bak")
        with _connect(path) as conn, sqlite3.connect(target) as destination:
            conn.backup(destination)
        print(f"backup -> {target}")
        return 0
    raise SystemExit(f"unknown db command {args.db_command!r}")


def _connect(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobcaliber", description="job offer ranker")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="project root (default: repo root)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="one fetch+score pass")
    run.add_argument("--limit", type=int, default=None, help="score at most N pending postings")
    run.add_argument("--engine", default=None, help="override the scorer engine")
    run.add_argument("--max-queries", type=int, default=None, help="use at most N search queries")
    run.add_argument("--trigger", default="cli", choices=["cli", "schedule", "manual"])
    run.add_argument("--dry-run", action="store_true", help="do everything without writing to the DB")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="last run and pending notifications")
    status.set_defaults(func=cmd_status)

    db = sub.add_parser("db", help="inspect and migrate the database")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("version", help="current schema version")
    db_migrate = db_sub.add_parser("migrate", help="apply pending migrations")
    db_migrate.add_argument("--to", type=int, default=None, help="stop at this version")
    db_migrate.add_argument("--dry-run", action="store_true", help="list the steps, change nothing")
    db_migrate.add_argument("--no-backup", action="store_true", help="skip the backup")
    db_sub.add_parser("check", help="compare the database with schema.sql")
    db_backup = db_sub.add_parser("backup", help="copy the database")
    db_backup.add_argument("--to", default=None, help="destination file")
    db.set_defaults(func=cmd_db)

    jobs = sub.add_parser("jobs", help="list stored postings")
    jobs.add_argument("--decision", choices=["pass", "review", "drop"])
    jobs.add_argument("--source")
    jobs.add_argument("--text")
    jobs.add_argument("--limit", type=int, default=20)
    jobs.set_defaults(func=cmd_jobs)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
