"""CLI: `python -m jobcaliber run|status`. The web app and the scheduler call the same code."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jobcaliber.application.runner import run_once
from jobcaliber.bootstrap import build_context

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
