"""The pipeline: fetch -> upsert -> score the pending postings -> evaluate -> persist."""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from jobcaliber.bootstrap import AppContext
from jobcaliber.core.domain import JobPosting
from jobcaliber.infrastructure.ai.client.base import EngineUnreachable
from jobcaliber.infrastructure.model_host import ModelHostUnreachable
from jobcaliber.infrastructure.database import RunStats
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
    failed: bool = False
    attempt: int = 1
    error: str | None = None
    retryable: bool = True


def run_once(
    ctx: AppContext,
    *,
    engine: str | None = None,
    limit: int | None = None,
    max_queries: int | None = None,
    trigger: str = "cli",
    dry_run: bool = False,
    run_id: int | None = None,
    fetcher=None,
    scorer=None,
    notifier=None,
    model_host=None,
    progress=print,
) -> RunOutcome:
    """Run one pass. `fetcher`/`scorer` are injectable so tests never touch the network."""
    started = time.time()
    config, store = ctx.config, ctx.store
    engine_name = engine or ctx.engine

    config_v = 0
    if not dry_run:
        config_v, _ = store.config_version(ctx.raw_yaml)
        if run_id is None:
            run_id = store.start_run(config_v, engine_name, trigger)
    else:
        run_id = None

    outcome = RunOutcome(run_id=run_id, config_v=config_v, engine=engine_name, dry_run=dry_run)
    stats = RunStats()
    host = model_host
    try:
        scorer = scorer or ctx.scorer(engine_name)
        if not dry_run:
            host = host if host is not None else ctx.model_host(engine_name, scorer.probe)
            if host is not None:
                host.ensure_ready()
            else:
                scorer.probe()
        fetcher = fetcher or Fetcher(config.scraping, config.search)
        queries = fetcher.build_queries()
        if max_queries:
            queries = queries[:max_queries]
        progress(f"queries: {len(queries)} · boards: {', '.join(fetcher.boards)} · config_v {config_v}")

        pending = _collect(ctx, fetcher, queries, stats, dry_run, progress)
        to_score = pending[:limit] if limit else pending
        progress(f"pending {len(pending)} · scoring {len(to_score)}")

        _score(ctx, scorer, to_score, run_id, config_v, engine_name, outcome, stats, dry_run, progress)
    except Exception as exc:
        outcome.retryable = not isinstance(exc, (EngineUnreachable, ModelHostUnreachable))
        stats.status = "failed"
        stats.error = f"{type(exc).__name__}: {exc}"
        outcome.failed = True
        outcome.error = stats.error
    finally:
        outcome.duration_ms = int((time.time() - started) * 1000)
        outcome.fetched, outcome.usable, outcome.new = stats.fetched, stats.usable, stats.new
        outcome.scored = stats.scored
        if not dry_run and run_id is not None:
            store.finish_run(run_id, stats, outcome.duration_ms)
        if not dry_run and host is not None:
            host.release()
    notifier = notifier or ctx.notifier
    if notifier and not dry_run and not outcome.failed:
        _notify(ctx, notifier, run_id, progress)
    return outcome


def _collect(ctx: AppContext, fetcher, queries, stats: RunStats, dry_run: bool,
             progress) -> list[JobPosting]:
    """Fetch every query/board; persist what is new; return what still needs scoring."""
    postings: list[JobPosting] = []
    for query in queries:
        for board in fetcher.boards:
            batch, board_stats = fetcher.fetch_board(query, board)
            postings.extend(batch)
            stats.fetched += board_stats.seen
            stats.usable += board_stats.usable
            stats.error = "; ".join(board_stats.errors) or stats.error
            if not dry_run:
                inserted = sum(int(ctx.store.upsert_posting(posting)[1]) for posting in batch)
                stats.new += inserted
                progress(f"{board} · {query.keywords} @ {query.location}: "
                         f"{len(batch)} rows · {inserted} new · {stats.new} new in this run")
    if dry_run:
        stats.new = len(postings)
        return postings
    progress(f"fetched {stats.fetched} rows ({stats.usable} usable)")
    return ctx.store.pending(_config_version(ctx), ctx.engine)


def _notify(ctx: AppContext, notifier, run_id: int | None, progress) -> None:
    """A digest of the new `pass` and `review` postings; a failure here never fails the run."""
    marked = ctx.store.applied_job_ids()
    rows = [row for row in ctx.store.new_notifiable() if row.id not in marked]
    if not rows:
        return
    error = notifier.send(rows, run_id)
    if error:
        progress(f"telegram: not sent ({error})")
        return
    ctx.store.mark_notified([row.id for row in rows])
    progress(f"telegram: {len(rows)} offers sent")


def _config_version(ctx: AppContext) -> int:
    return ctx.store.config_version(ctx.raw_yaml)[0]


def _score(ctx: AppContext, scorer, postings: list[JobPosting], run_id: int | None, config_v: int,
           engine: str, outcome: RunOutcome, stats: RunStats, dry_run: bool, progress) -> None:
    evaluator = Evaluator(ctx.config)
    for index, posting in enumerate(postings, start=1):
        result = scorer.score_posting(posting)
        evaluation = evaluator.evaluate(result)
        outcome.decisions[evaluation.decision.value] += 1
        stats.scored += 1
        if not dry_run:
            job_id, _ = ctx.store.upsert_posting(posting)
            ctx.store.save_evaluation(job_id, run_id, config_v, engine, result, evaluation)
        progress(
            f"[{index}/{len(postings)}] {evaluation.decision.value.upper():6} "
            f"{evaluation.score_total:5.1f} {posting.title[:60]}"
        )
