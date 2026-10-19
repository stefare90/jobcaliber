"""Spike 02 — compare: build a cross-engine report from the measured runs.

Reads every output/results-<engine>.json written by engine_benchmark.py and writes
output/comparison.md: decision mix, score spread (discrimination), latency, per-posting
decisions and a pairwise agreement matrix.

Independent from the runner on purpose: re-render the comparison without re-scoring, and
compare as soon as a new engine has been measured. Refuses to mix runs measured on a
different dataset or limit.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTPUT_DIR = HERE / "output"
REPORT_PATH = OUTPUT_DIR / "comparison.md"

DECISIONS = ("pass", "review", "drop")


def load_results(names: list[str] | None) -> list[dict]:
    files = sorted(OUTPUT_DIR.glob("results-*.json"))
    if names:
        files = [f for f in files if f.stem.removeprefix("results-") in names]
    if not files:
        raise SystemExit(f"no results-*.json in {OUTPUT_DIR}; run engine_benchmark.py first")
    results = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("postings"):
            print(f"skipped {path.name}: no scored postings (engine failed)")
            continue
        results.append(data)
    if not results:
        raise SystemExit("every results file is empty")
    return results


def check_same_dataset(results: list[dict]) -> tuple[str, int]:
    shas = {r["dataset_sha"] for r in results}
    limits = {r["limit"] for r in results}
    if len(shas) > 1 or len(limits) > 1:
        details = "\n".join(
            f"- {r['engine']}: dataset={r['dataset_sha']} limit={r['limit']} "
            f"({len(r['postings'])} scored)" for r in results
        )
        raise SystemExit(
            "refusing to compare runs measured on different inputs "
            f"(dataset_sha={sorted(shas)}, limit={sorted(limits)}):\n{details}"
        )
    return results[0]["dataset"], results[0]["limit"]


def decision_counts(result: dict) -> dict[str, int]:
    counts = {d: 0 for d in DECISIONS}
    for row in result["postings"]:
        counts[row["decision"].lower()] = counts.get(row["decision"].lower(), 0) + 1
    return counts


def scores(result: dict) -> list[float]:
    return [row["score"] for row in result["postings"]]


def render_comparison(results: list[dict], dataset: str, limit: int) -> str:
    reference = results[0]["postings"]
    by_engine = {r["engine"]: {row["external_id"]: row for row in r["postings"]} for r in results}

    lines = [
        "# Spike 02 — cross-engine comparison",
        "",
        f"- generated_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"- input: `{dataset}` · limit {limit} · dataset_sha `{results[0]['dataset_sha']}`",
        f"- engines: {', '.join(f'`{r["engine"]}`' for r in results)}",
        "",
        "## Summary",
        "",
        "| engine | model | api | PASS | REVIEW | DROP | mean score | stdev | min-max | mean latency | failures |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        counts = decision_counts(r)
        values = scores(r)
        latency = [row["latency_s"] for row in r["postings"]]
        lines.append(
            f"| `{r['engine']}` | `{r['model']}` | `{r['api']}` | {counts['pass']} | {counts['review']} | "
            f"{counts['drop']} | {statistics.mean(values):.1f} | "
            f"{statistics.pstdev(values):.1f} | {min(values):.0f}-{max(values):.0f} | "
            f"{statistics.mean(latency):.2f}s | {r['failures']} |"
        )

    lines += [
        "",
        "Discrimination = `stdev` of the scores: a flat engine (near 0) does not separate",
        "good from bad offers even if its mean looks sane.",
        "",
        "## Agreement (same decision on the same posting)",
        "",
        "| pair | agreement | postings |",
        "|---|---|---|",
    ]
    for a, b in combinations(results, 2):
        left, right = by_engine[a["engine"]], by_engine[b["engine"]]
        shared = sorted(set(left) & set(right))
        same = sum(1 for k in shared if left[k]["decision"].lower() == right[k]["decision"].lower())
        pct = 100 * same / len(shared) if shared else 0.0
        lines.append(f"| `{a['engine']}` vs `{b['engine']}` | {pct:.0f}% | {len(shared)} |")

    lines += [
        "",
        "## Per posting",
        "",
        "Each posting links to the original ad, so a decision can be checked against the text.",
        "",
        "| # | posting | " + " | ".join(f"`{r['engine']}`" for r in results) + " |",
        "|---|---|" + "---|" * len(results),
    ]
    for i, row in enumerate(reference, start=1):
        label = f"{row['title'][:46]} @ {row['company'][:22]}"
        url = row.get("url") or next(
            (r["url"] for r in (by_engine[e].get(row["external_id"]) or {} for e in by_engine) if r), ""
        )
        title = f"[{label}]({url})" if url else label
        cells = []
        for r in results:
            cell = by_engine[r["engine"]].get(row["external_id"])
            cells.append(f"{cell['decision'].upper()} {cell['score']:.0f}" if cell else "—")
        lines.append(f"| {i} | {title} | " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engines", nargs="*", help="optional subset; default: every results-*.json")
    args = parser.parse_args()

    results = load_results(args.engines or None)
    dataset, limit = check_same_dataset(results)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_comparison(results, dataset, limit), encoding="utf-8")
    print(render_comparison(results, dataset, limit))
    print(f"-> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
