"""Spike 01 — fetch coverage: how many usable offers each query x board returns.

Reads the query matrix from `search`, fetches every board sequentially, and writes:
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
STATS_PATH = OUTPUT_DIR / "stats.json"
BENCH_POSTINGS = HERE.parent / "02_engine_benchmark" / "input" / "postings.jsonl"

# Reporting bar: below this a query cannot sustain a daily pipeline. Reported per query,
# it does not turn the run into a pass/fail verdict.
MIN_USABLE_PER_QUERY = 5


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
    captcha_skipped: int,
    reconstructed: bool = False,
) -> str:
    usable = {qid: stats["usable"] for qid, stats in per_query.items()}
    usable_total = sum(usable.values())

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
        "- coverage rebuilt from `output/raw/`: captcha and error counters were not persisted"
        " by that run" if reconstructed else "",
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
        "| board | seen | usable | new | captcha skipped | errors |",
        "|---|---|---|---|---|---|",
    ]
    for board in fetcher.boards:
        stats = per_board.get(board, {"seen": 0, "usable": 0, "new": 0, "captcha_skipped": 0, "errors": []})
        lines.append(
            f"| {board} | {stats['seen']} | {stats['usable']} | {stats['new']} | "
            f"{stats.get('captcha_skipped', 0)} | {len(stats['errors'])} |"
        )
    errors = [(board, err) for board, stats in per_board.items() for err in stats["errors"]]
    if errors:
        lines += ["", "### Errors"]
        lines += [f"- {board}: {err}" for board, err in errors]

    below = [f"`{qid}` {count}" for qid, count in usable.items() if count < MIN_USABLE_PER_QUERY]
    lines += [
        "",
        "## Coverage",
        "",
        f"- usable rows per query below {MIN_USABLE_PER_QUERY}: {', '.join(below) or 'none'}",
        f"- queries with zero rows: {', '.join(q for q, c in usable.items() if c == 0) or 'none'}",
        f"- captcha rows skipped: {captcha_skipped}",
        f"- total usable rows: {usable_total}",
        f"- frozen benchmark set: {exported[1]} postings deduplicated from {exported[0]} rows "
        f"-> `{BENCH_POSTINGS.relative_to(ROOT)}`",
        "",
    ]
    return "\n".join(lines)


def reconstruct_from_raw(queries: list[Query]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Rebuild per-query/per-board counters by replaying output/raw/ in fetch order."""
    per_query = {f"q{i}": {"seen": 0, "usable": 0, "new": 0} for i in range(1, len(queries) + 1)}
    per_board: dict[str, dict] = {}
    seen: set[str] = set()
    for index, query in enumerate(queries, start=1):
        qid = f"q{index}"
        path_list = sorted(RAW_DIR.glob(f"{qid}_*.json"))
        for path in path_list:
            board = path.stem.split("_", 1)[1]
            bucket = per_board.setdefault(
                board, {"seen": 0, "usable": 0, "new": 0, "captcha_skipped": 0, "errors": []}
            )
            rows = json.loads(path.read_text(encoding="utf-8"))
            bucket["seen"] += len(rows)
            per_query[qid]["seen"] += len(rows)
            for row in rows:
                if row.get("title") and row.get("company") and row.get("url"):
                    bucket["usable"] += 1
                    per_query[qid]["usable"] += 1
                key = row.get("external_id")
                if key and key not in seen:
                    seen.add(key)
                    bucket["new"] += 1
                    per_query[qid]["new"] += 1
    return per_query, per_board


def load_queries_snapshot() -> list[Query]:
    data = json.loads((INPUT_DIR / "queries.json").read_text(encoding="utf-8"))
    return [Query(keywords=q["keywords"], location=q["location"], role=q["role"], remote=q["remote"])
            for q in data["queries"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="skip the network and only rebuild the benchmark set from output/raw/",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="skip the network and rebuild report.md from output/raw/ (captcha/errors unknown)",
    )
    args = parser.parse_args()

    if args.report_only:
        config_path, config = load_config(ROOT)
        queries = load_queries_snapshot()
        per_query, per_board = reconstruct_from_raw(queries)
        exported = export_postings(RAW_DIR, BENCH_POSTINGS)
        report = render_report(
            "not recorded (rebuilt from output/raw/)", config_path, config, Fetcher(config.scraping), queries,
            per_query, per_board, exported, captcha_skipped=0, reconstructed=True,
        )
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(report)
        return 0

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
    queries = fetcher.build_queries(config.search)
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
            bucket = per_board.setdefault(
                board, {"seen": 0, "usable": 0, "new": 0, "captcha_skipped": 0, "errors": []}
            )
            bucket["seen"] += stats.seen
            bucket["usable"] += stats.usable
            bucket["new"] += stats.new
            bucket["errors"].extend(stats.errors)
            bucket["captcha_skipped"] += stats.captcha_skipped

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
    captcha_skipped = sum(stats["captcha_skipped"] for stats in per_board.values())
    STATS_PATH.write_text(
        json.dumps(
            {
                "started_utc": started,
                "config": config_path.name,
                "queries": per_query,
                "boards": per_board,
                "captcha_skipped": captcha_skipped,
                "exported": {"rows": exported[0], "unique": exported[1]},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = render_report(
        started, config_path, config, fetcher, queries, per_query, per_board, exported, captcha_skipped
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
