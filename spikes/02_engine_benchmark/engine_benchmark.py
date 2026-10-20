"""Spike 02 — engine benchmark: which System One engine discriminates best, at what latency.

Reads the frozen posting set produced by spike 01 (input/postings.jsonl), scores each
posting with one engine from config.ai.engines, and writes output/report-<engine>.md.
Same input for every engine, so the leaderboards are comparable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jobcaliber.ai import AIClients
from jobcaliber.config import AppConfig, AIEngine, load_config
from jobcaliber.models import GateDecision, JobPosting
from jobcaliber.scoring import Evaluator

HERE = Path(__file__).resolve().parent
INPUT_PATH = HERE / "input" / "postings.jsonl"
OUTPUT_DIR = HERE / "output"


def dataset_sha(path: Path = INPUT_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_postings(path: Path = INPUT_PATH) -> list[JobPosting]:
    if not path.exists():
        raise SystemExit(
            f"missing {path}; run spikes/01_fetch_coverage/fetch_coverage.py first"
        )
    text = path.read_text(encoding="utf-8")
    rows = json.loads(text) if text.lstrip().startswith("[") else [
        json.loads(line) for line in text.splitlines() if line.strip()
    ]
    postings: list[JobPosting] = []
    for row in rows:
        postings.append(
            JobPosting(
                external_id=row["external_id"],
                url=row.get("url") or "",
                title=row.get("title") or "",
                company=row.get("company") or "",
                source=row.get("source") or "",
                location_raw=row.get("location_raw"),
                description=row.get("description"),
                salary_min=row.get("salary_min"),
                salary_max=row.get("salary_max"),
                posted_at=row.get("posted_at"),
                search_id=row.get("search_id"),
            )
        )
    return postings


def render_report(
    engine_name: str,
    engine: AIEngine,
    results: list[tuple[JobPosting, object, object, float]],
    total: float,
) -> str:
    passed = sum(1 for *_, ev, _ in results if ev.decision == GateDecision.PASS)
    review = sum(1 for *_, ev, _ in results if ev.decision == GateDecision.REVIEW)
    dropped = sum(1 for *_, ev, _ in results if ev.decision == GateDecision.DROP)
    times = [r[3] for r in results]

    lines = [
        f"# Spike 02 — engine benchmark: {engine_name}",
        "",
        f"- engine: `{engine_name}` · kind `{engine.kind}` · api `{engine.api}`",
        f"- model: `{engine.model}` · url: `{engine.base_url}`",
        f"- input: `{INPUT_PATH.relative_to(ROOT)}`",
        f"- evaluated: {len(results)} postings",
        f"- total: {total:.1f}s · mean: {sum(times) / len(times):.2f}s · "
        f"min: {min(times):.2f}s · max: {max(times):.2f}s",
        "",
        "## Summary",
        "",
        f"- PASS (>= notify threshold): {passed}",
        f"- REVIEW: {review}",
        f"- DROP: {dropped}",
        "",
        "## Leaderboard",
        "",
        "| # | Decision | Score | Conf | Time | Title | Company | Location | Missing | URL |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, (job, s1, ev, dt) in enumerate(results, start=1):
        url = f"[link]({job.url})" if job.url else "-"
        lines.append(
            f"| {rank} | `{ev.decision.value.upper()}` | **{ev.score_total}** | {ev.confidence:.2f} | {dt:.2f}s | "
            f"{job.title.replace('|', '-')} | {job.company.replace('|', '-')} | "
            f"{(job.location_raw or '').replace('|', '-')} | {', '.join(sorted(s1.missing)) or '-'} | {url} |"
        )

    lines += ["", "## Details", ""]
    for rank, (job, s1, ev, dt) in enumerate(results, start=1):
        subs = ev.sub_scores
        answers = ", ".join(f"{key} `{value}`" for key, value in s1.answers.items())
        lines += [
            f"### #{rank} [{ev.decision.value.upper()}] {job.title} — {job.company}",
            f"- score **{ev.score_total}** · conf {ev.confidence:.2f} · {dt:.2f}s",
            f"- location: `{job.location_raw}`",
            f"- answers: {answers}",
            f"- weighted sub-scores: " + " · ".join(f"{k} `{v}`" for k, v in subs.items()),
            f"- missing: {', '.join(sorted(s1.missing)) or 'none'}",
            f"- dropped by: {ev.dropped_by or '-'}",
            f"- reasons: {', '.join(ev.reasons) or '-'}",
            f"- url: {job.url or '-'}",
            "",
        ]
    return "\n".join(lines)


def write_results(
    engine_name: str, engine: AIEngine, results: list[tuple[JobPosting, object, object, float]],
    total: float, failures: int, limit: int, dataset: Path = INPUT_PATH,
) -> Path:
    payload = {
        "engine": engine_name,
        "model": engine.model,
        "api": engine.api,
        "kind": engine.kind,
        "base_url": engine.base_url,
        "options": engine.options,
        "dataset": dataset.name,
        "dataset_sha": dataset_sha(dataset),
        "limit": limit,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_s": round(total, 2),
        "failures": failures,
        "postings": [
            {
                "external_id": job.external_id,
                "url": job.url,
                "title": job.title,
                "company": job.company,
                "decision": ev.decision.value,
                "score": ev.score_total,
                "confidence": ev.confidence,
                "sub_scores": ev.sub_scores,
                "answers": {k: v for k, v in s1.answers.items()},
                "missing": sorted(s1.missing),
                "dropped_by": ev.dropped_by,
                "latency_s": round(dt, 2),
            }
            for job, s1, ev, dt in sorted(results, key=lambda t: t[0].external_id)
        ],
    }
    path = OUTPUT_DIR / f"results-{engine_name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_engine(
    engine_name: str, postings: list[JobPosting], config: AppConfig, limit: int,
    dataset: Path = INPUT_PATH,
) -> tuple[Path, int, float]:
    ai = AIClients.from_config(config.ai, ROOT)
    engine = config.ai.engines[engine_name]
    scorer = ai.scorer_for(engine_name, config.criteria, config.search.render_values())
    evaluator = Evaluator(config)
    print(f"=== {engine_name} ({engine.model} @ {engine.base_url}) — {len(postings)} postings ===")

    results: list[tuple[JobPosting, object, object, float]] = []
    failures = 0
    started = time.time()
    for i, job in enumerate(postings, start=1):
        t0 = time.time()
        try:
            s1 = scorer.score_posting(job)
            ev = evaluator.evaluate(s1)
        except Exception as e:
            failures += 1
            print(f"[{i:2}/{len(postings)}] ERROR {job.title[:40]}: {e}")
            continue
        dt = time.time() - t0
        results.append((job, s1, ev, dt))
        print(
            f"[{i:2}/{len(postings)}] {dt:5.2f}s "
            f"[{ev.decision.value.upper():6}] {ev.score_total:5.1f} | {job.title[:55]} @ {job.company[:25]}"
        )
    total = time.time() - started

    results.sort(key=lambda t: (t[2].score_total, t[2].confidence), reverse=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"report-{engine_name}.md"
    if results:
        report_path.write_text(render_report(engine_name, engine, results, total), encoding="utf-8")
        print(f"-> {report_path} ({total:.1f}s total, {total / len(results):.2f}s mean)")
    results_path = write_results(engine_name, engine, results, total, failures, limit, dataset)
    print(f"-> {results_path}")
    return report_path, failures, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--input", type=Path, default=INPUT_PATH,
                        help="postings file (jsonl, or a json array), e.g. the calibration sample")
    args = parser.parse_args()

    _, config = load_config(ROOT)
    if args.engine not in config.ai.engines:
        parser.error(f"unknown engine '{args.engine}'; available: {list(config.ai.engines)}")

    postings = load_postings(args.input)[: args.limit]
    print(f"loaded {len(postings)} postings from {args.input}")
    _, failures, _ = run_engine(args.engine, postings, config, args.limit, args.input)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
