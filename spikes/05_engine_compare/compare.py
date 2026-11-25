"""Score the same postings with a candidate engine and compare criterion by criterion.

Read-only: nothing is written to the database. The baseline engine's answers come from the stored
evaluations, so the sample is whatever the archive already judged; the candidate answers them again.

    uv run python spikes/05_engine_compare/compare.py --limit 20
"""
from __future__ import annotations

import argparse
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from jobcaliber.bootstrap import build_context  # noqa: E402
from jobcaliber.infrastructure.database.store import Store  # noqa: E402
from jobcaliber.pipeline.evaluation.evaluator import Evaluator  # noqa: E402

ORDER = {"pass": 2, "review": 1, "drop": 0}


def sample_ids(ctx, baseline: str, limit: int) -> list[int]:
    with ctx.store.connect() as conn:
        rows = conn.execute(
            "SELECT j.id FROM jobs j JOIN evaluations e ON e.id = ("
            "  SELECT MAX(id) FROM evaluations e2 WHERE e2.job_id = j.id) "
            "WHERE e.engine = ? AND j.description IS NOT NULL AND LENGTH(j.description) > 200 "
            "ORDER BY RANDOM() LIMIT ?",
            (baseline, limit),
        ).fetchall()
    return [row["id"] for row in rows]


def baseline_answers(ctx, job_id: int, engine: str) -> dict[str, str]:
    with ctx.store.connect() as conn:
        row = conn.execute(
            "SELECT e.id FROM evaluations e WHERE e.job_id = ? AND e.engine = ? "
            "ORDER BY e.id DESC LIMIT 1",
            (job_id, engine),
        ).fetchone()
        if row is None:
            return {}
        answers = conn.execute(
            "SELECT criterion, value, option FROM evaluation_answers WHERE evaluation_id = ?",
            (row["id"],),
        ).fetchall()
    return {a["criterion"]: (a["option"] if a["option"] is not None else a["value"]) for a in answers}


def comparable(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--candidate", default="opencode_llm")
    parser.add_argument("--baseline", default="rizzo")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--ids", default="", help="comma separated job ids: re-use a fixed sample")
    args = parser.parse_args()

    ctx = build_context(pathlib.Path(args.root))
    evaluator = Evaluator(ctx.config)
    scorer = ctx.scorer(args.candidate)

    ids = [int(part) for part in args.ids.split(",") if part.strip()] or \
        sample_ids(ctx, args.baseline, args.limit)
    print("ids: " + ",".join(str(job_id) for job_id in ids))
    print(f"{len(ids)} postings · baseline {args.baseline} vs candidate {args.candidate}\n")

    latencies: list[float] = []
    deltas: list[float] = []
    same_decision = 0
    per_criterion: dict[str, list[bool]] = {}
    harsher: list[str] = []
    softer: list[str] = []
    failures = 0

    for job_id in ids:
        job = ctx.store.job(job_id)
        if job is None:
            continue
        posting = Store._to_posting(job)
        with ctx.store.connect() as conn:
            before = conn.execute(
                "SELECT decision, score_total, dropped_by FROM evaluations WHERE job_id = ? "
                "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        old_answers = baseline_answers(ctx, job_id, args.baseline)
        started = time.time()
        try:
            result = scorer.score_posting(posting)
        except Exception as error:  # one bad answer must not abort the sample
            failures += 1
            print(f"  ! {error.__class__.__name__}: {str(error)[:100]}")
            continue
        elapsed = time.time() - started
        latencies.append(elapsed)
        after = evaluator.evaluate(result)

        old, new = before["decision"], after.decision.value
        old_score, new_score = before["score_total"] or 0.0, after.score_total
        deltas.append(abs(new_score - old_score))
        same_decision += int(old == new)
        if ORDER.get(new, 0) > ORDER.get(old, 0):
            softer.append(f"{posting.title[:50]} ({old} → {new}, dropped_by {after.dropped_by})")
        elif ORDER.get(new, 0) < ORDER.get(old, 0):
            harsher.append(f"{posting.title[:50]} ({old} → {new}, dropped_by {after.dropped_by})")

        for key, value in result.answers.items():
            if key not in old_answers:
                continue
            per_criterion.setdefault(key, []).append(comparable(value) == comparable(old_answers[key]))

        print(f"{' ' if old == new else '≠'} {old:6} {old_score:5.1f} → {new:6} {new_score:5.1f} "
              f"by {str(after.dropped_by or '-'):10} {elapsed:5.1f}s  {posting.title[:44]}")

    total = len(deltas)
    print(f"\ndecisions agree: {same_decision}/{total} ({100 * same_decision / max(total, 1):.0f}%)"
          f" · failures {failures}")
    print(f"mean |Δscore|: {statistics.fmean(deltas) if deltas else 0:.1f}")
    if latencies:
        print(f"latency: mean {statistics.fmean(latencies):.1f}s · median {statistics.median(latencies):.1f}s"
              f" · max {max(latencies):.1f}s")
        print(f"full run estimate for 1600 postings: {statistics.fmean(latencies) * 1600 / 3600:.1f} h")
    print("\nagreement per criterion:")
    for key, results in sorted(per_criterion.items(), key=lambda kv: -len(kv[1])):
        print(f"  {key:14} {sum(results):3}/{len(results):3}  ({100 * sum(results) / len(results):3.0f}%)")
    if harsher:
        print("\ncandidate is STRICTER on:")
        for line in harsher:
            print(f"  {line}")
    if softer:
        print("\ncandidate is SOFTER on:")
        for line in softer:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
