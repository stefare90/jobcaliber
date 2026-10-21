"""The pipeline: fetch -> upsert -> score the pending postings -> evaluate -> persist."""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from jobcaliber.bootstrap import AppContext
from jobcaliber.infrastructure.persistence import RunStats, Store
from jobcaliber.pipeline.evaluation import Evaluator
from jobcaliber.pipeline.fetch import Fetcher


@dataclass
class RunOutcome:
    run_id: int | None
    config_v: int
    engine: str
    fetched: int = 0
    usable: int = 0
    new: int = 0
    scored: int = 0
    decisions: Counter = field(default_factory=Counter)
    duration_ms: int = 0
    dry_run: bool = False


def run_once(
    ctx: AppContext,
    *,
    engine: str | None = None,
    limit: int | None = None,
    max_queries: int | None = None,
    trigger: str = "cli",
    dry_run: bool = False,
    fetcher=None,
    scorer=None,
    progress=print,
) -> RunOutcome:
    """Run one pass. `fetcher`/`scorer` are injectable so tests never touch the network."""
    started = time.time()
    config, store = ctx.config, ctx.store
    engine_name = engine or ctx.engine

    config_v = 0
    if not dry_run:
        store.fail_stale_runs()
        config_v, _ = store.config_version(ctx.raw_yaml)
        run_id = store.start_run(config_v, engine_name, trigger)
    else:
        run_id = None

    outcome = RunOutcome(run_id=run_id, config_v=config_v, engine=engine_name, dry_run=dry_run)
    stats = RunStats()
    try:
        fetcher = fetcher or Fetcher(config.scraping)
        queries = fetcher.build_queries(config.search)
        if max_queries:
            queries = queries[:max_queries]
        progress(f"queries: {len(queries)} · boards: {', '.join(fetcher.boards)} · config_v {config_v}")

        if not dry_run:
            postings = []
            for query in queries:
                for board in fetcher.boards:
                    batch, board_stats = fetcher.fetch_board(query, board)
                    postings.extend(batch)
                    stats.fetched += board_stats.seen
                    stats.usable += board_stats.usable
                    stats.error = "; ".join(board_stats.errors) or stats.error
            progress(f"fetched {stats.fetched} rows ({stats.usable} usable)")
            for posting in postings:
                _, is_new = store.upsert_posting(posting)
                stats.new += int(is_new)
            pending = store.pending(config_v, engine_name)
        else:
            pending = []
            for query in queries:
                for board in fetcher.boards:
                    batch, board_stats = fetcher.fetch_board(query, board)
                    pending.extend(batch)
                    stats.fetched += board_stats.seen
                    stats.usable += board_stats.usable
            stats.new = len(pending)

        to_score = pending[:limit] if limit else pending
        progress(f"pending {len(pending)} · scoring {len(to_score)}")

        scorer = scorer or ctx.scorer(engine_name)
        evaluator = Evaluator(config)
        for index, posting in enumerate(to_score, start=1):
            result = scorer.score_posting(posting)
            evaluation = evaluator.evaluate(result)
            outcome.decisions[evaluation.decision.value] += 1
            stats.scored += 1
            if not dry_run:
                job_id, _ = store.upsert_posting(posting)
                store.save_evaluation(job_id, run_id, config_v, engine_name, result, evaluation)
            progress(
                f"[{index}/{len(to_score)}] {evaluation.decision.value.upper():6} "
                f"{evaluation.score_total:5.1f} {posting.title[:60]}"
            )
    except Exception as exc:
        stats.status = "failed"
        stats.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        outcome.duration_ms = int((time.time() - started) * 1000)
        outcome.fetched, outcome.usable, outcome.new = stats.fetched, stats.usable, stats.new
        outcome.scored = stats.scored
        if not dry_run and run_id is not None:
            store.finish_run(run_id, stats, outcome.duration_ms)
    return outcome
