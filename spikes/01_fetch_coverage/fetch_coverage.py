"""Spike 01 — fetch coverage: how many usable offers each query x board returns.

Reads the query matrix from the profile, fetches every board sequentially, and writes:
  input/queries.json                                  the matrix actually used
  output/raw/q<idx>_<board>.json                      raw postings, one file per query/board
  output/report.md                                    coverage report + pass bar
  ../02_engine_benchmark/input/postings.jsonl         frozen, deduplicated posting set

No scoring happens here: this spike answers "do the queries reach enough offers?".
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jobcaliber.config import AppConfig, load_config
from jobcaliber.ingestion.fetch import Fetcher
from jobcaliber.models import JobPosting, Query

HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "input"
OUTPUT_DIR = HERE / "output"
RAW_DIR = OUTPUT_DIR / "raw"
REPORT_PATH = OUTPUT_DIR / "report.md"
BENCH_POSTINGS = HERE.parent / "02_engine_benchmark" / "input" / "postings.jsonl"

PASS_BAR_USABLE_PER_QUERY = 5


def postings_to_json(postings: list[JobPosting]) -> list[dict]:
    return [
        {
            "external_id": p.external_id,
            "url": p.url,
            "title": p.title,
            "company": p.company,
            "source": p.source,
            "location_raw": p.location_raw,
            "description": p.description,
            "salary_min": p.salary_min,
            "salary_max": p.salary_max,
            "posted_at": p.posted_at,
            "search_id": p.search_id,
        }
        for p in postings
    ]


def write_queries_snapshot(queries: list[Query], fetcher: Fetcher, config: AppConfig) -> Path:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "boards": list(fetcher.boards),
        "page_size": fetcher.page_size,
        "board_max_results": {b: fetcher.scraping.max_results(b) for b in fetcher.boards},
        "country": config.scraping.country,
        "hours_old": config.scraping.hours_old,
        "job_type": config.scraping.job_type,
        "queries": [
            {
                "id": f"q{i}",
                "keywords": q.keywords,
                "location": q.location,
                "role": q.role,
                "remote": q.remote,
            }
            for i, q in enumerate(queries, start=1)
        ],
    }
    path = INPUT_DIR / "queries.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def export_postings(raw_dir: Path, target: Path) -> tuple[int, int]:
    """Deduplicate the raw rows by external_id into the frozen benchmark set."""
    seen: set[str] = set()
    unique: list[dict] = []
    total = 0
    for path in sorted(raw_dir.glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            total += 1
            key = row.get("external_id") or row.get("url")
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(row)
    unique.sort(key=lambda r: r["external_id"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in unique), encoding="utf-8"
    )
    return total, len(unique)


def render_report(
    started: str,
    config_path: Path,
    config: AppConfig,
    fetcher: Fetcher,
    queries: list[Query],
    per_query: dict[str, dict],
    per_board: dict[str, dict],
    exported: tuple[int, int],
) -> str:
    usable_per_query = {qid: stats["usable"] for qid, stats in per_query.items()}
    pass_bar = all(v >= PASS_BAR_USABLE_PER_QUERY for v in usable_per_query.values())
    usable_total = sum(usable_per_query.values())

    lines = [
        "# Spike 01 — fetch coverage",
        "",
        f"- started_utc: {started}",
        f"- config: {config_path.name}",
        f"- params: country_indeed={config.scraping.country}, hours_old={config.scraping.hours_old}, "
        f"page={fetcher.page_size} max={{{', '.join(f'{b}: {fetcher.scraping.max_results(b)}' for b in fetcher.boards)}}} "
        f"job_type={config.scraping.job_type}",
        f"- boards: {', '.join(fetcher.boards)}",
        f"- queries: {len(queries)}",
        "",
        "## Queries",
        "",
        "| id | keywords | location | remote | seen | usable | new |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, query in enumerate(queries, start=1):
        stats = per_query[f"q{i}"]
        lines.append(
            f"| q{i} | {query.keywords} | {query.location} | {query.remote} | "
            f"{stats['seen']} | {stats['usable']} | {stats['new']} |"
        )

    lines += [
        "",
        "## Per board",
        "",
        "| board | seen | usable | new | errors |",
        "|---|---|---|---|---|",
    ]
    for board in fetcher.boards:
        stats = per_board.get(board, {"seen": 0, "usable": 0, "new": 0, "errors": []})
        lines.append(
            f"| {board} | {stats['seen']} | {stats['usable']} | {stats['new']} | {len(stats['errors'])} |"
        )
    errors = [(board, err) for board, stats in per_board.items() for err in stats["errors"]]
    if errors:
        lines += ["", "### Errors"]
        lines += [f"- {board}: {err}" for board, err in errors]

    empty = [qid for qid, v in usable_per_query.items() if v == 0]
    lines += [
        "",
        "## Pass bar",
        "",
        f"- >= {PASS_BAR_USABLE_PER_QUERY} usable rows per query: "
        f"{'YES' if pass_bar else 'NO'}" + (f" (empty: {', '.join(empty)})" if empty else ""),
        f"- total usable rows: {usable_total}",
        f"- frozen benchmark set: {exported[1]} postings deduplicated from {exported[0]} rows "
        f"-> `{BENCH_POSTINGS.relative_to(ROOT)}`",
        f"- VERDICT: {'PASS' if pass_bar else 'FAIL'}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="skip the network and only rebuild the benchmark set from output/raw/",
    )
    args = parser.parse_args()

    if args.export_only:
        total, unique = export_postings(RAW_DIR, BENCH_POSTINGS)
        print(f"exported {unique} postings from {total} raw rows -> {BENCH_POSTINGS}")
        return 0

    started = datetime.now(timezone.utc).isoformat()
    config_path, config = load_config(ROOT)
    fetcher = Fetcher(
        config.scraping,
        on_page=lambda query, board, offset, seen: print(
            f"[page] {query.keywords} @ {query.location} / {board}: offset={offset} seen={seen}",
            flush=True,
        ),
    )
    queries = fetcher.build_queries(config.profile)
    snapshot_path = write_queries_snapshot(queries, fetcher, config)
    print(f"queries: {len(queries)} -> {snapshot_path}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for stale in RAW_DIR.glob("*.json"):
        stale.unlink()
    per_query: dict[str, dict] = {f"q{i}": {"seen": 0, "usable": 0, "new": 0} for i in range(1, len(queries) + 1)}
    per_board: dict[str, dict] = {}
    seen_ids: set[str] = set()

    for i, query in enumerate(queries, start=1):
        for board in fetcher.boards:
            postings, stats = fetcher.fetch_board(query, board, f"q{i}")
            (RAW_DIR / f"q{i}_{board}.json").write_text(
                json.dumps(postings_to_json(postings), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            bucket = per_board.setdefault(board, {"seen": 0, "usable": 0, "new": 0, "errors": []})
            bucket["seen"] += stats.seen
            bucket["usable"] += stats.usable
            bucket["new"] += stats.new
            bucket["errors"].extend(stats.errors)

            stats_q = per_query[f"q{i}"]
            stats_q["seen"] += len(postings)
            for posting in postings:
                if posting.title and posting.company and posting.url:
                    stats_q["usable"] += 1
                if posting.external_id not in seen_ids:
                    seen_ids.add(posting.external_id)
                    stats_q["new"] += 1

            print(
                f"[q{i}/{board}] seen={stats.seen} usable={stats.usable} new={stats.new}",
                flush=True,
            )
            fetcher.sleep_fn(2)

    exported = export_postings(RAW_DIR, BENCH_POSTINGS)
    report = render_report(started, config_path, config, fetcher, queries, per_query, per_board, exported)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    return 0 if "VERDICT: PASS" in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
