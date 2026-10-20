"""Spike 03 — sample: build a deterministic, stratified calibration set.

The benchmark set is ordered by `external_id`, so "the first 20" is an alphabetical slice of
URLs, not a sample. This picks `per_stratum` postings from every (query, board) pair with a
fixed seed, so the calibration set is stable and covers all queries.

Writes output/sample.json (full rows) and output/sample.tsv (title/company/url/description
truncated, for reading and labelling).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "spikes" / "02_engine_benchmark" / "input" / "postings.jsonl"
OUTPUT_DIR = HERE / "output"


def load_rows(path: Path = INPUT_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing {path}; run spikes/01_fetch_coverage/fetch_coverage.py first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def stratified_sample(rows: list[dict], per_stratum: int, seed: int) -> list[dict]:
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        strata[(row.get("search_id") or "?", row.get("source") or "?")].append(row)
    rng = random.Random(seed)
    picked: list[dict] = []
    for key in sorted(strata):
        bucket = sorted(strata[key], key=lambda r: r["external_id"])
        picked.extend(rng.sample(bucket, min(per_stratum, len(bucket))))
    picked.sort(key=lambda r: (r.get("search_id") or "", r["external_id"]))
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-stratum", type=int, default=6, help="postings per (query, board)")
    parser.add_argument("--seed", type=int, default=20261020)
    args = parser.parse_args()

    rows = load_rows()
    sample = stratified_sample(rows, args.per_stratum, args.seed)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "sample.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    lines = ["idx\tquery\tboard\tid\ttitle\tcompany\tlocation\tsalary\tdescription"]
    for i, row in enumerate(sample, start=1):
        salary = f"{row.get('salary_min') or ''}-{row.get('salary_max') or ''}".strip("-") or "-"
        description = (row.get("description") or "").replace("\n", " ").replace("\t", " ")
        lines.append(
            "\t".join([
                str(i), row.get("search_id") or "?", row.get("source") or "?", row["external_id"],
                row["title"].replace("\t", " "), row["company"].replace("\t", " "),
                (row.get("location_raw") or "-").replace("\t", " "), salary, description,
            ])
        )
    (OUTPUT_DIR / "sample.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    strata = defaultdict(int)
    for row in sample:
        strata[(row.get("search_id"), row.get("source"))] += 1
    print(f"pool: {len(rows)} postings · sample: {len(sample)} · seed {args.seed}")
    print("strata (query, board) -> picked:", dict(sorted(strata.items())))
    print(f"-> {OUTPUT_DIR / 'sample.json'}")
    print(f"-> {OUTPUT_DIR / 'sample.tsv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
