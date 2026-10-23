"""The worker: owns the schedule, claims queued runs, executes them one at a time."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from jobcaliber.application.runner import RunOutcome, run_once
from jobcaliber.application.schedule import is_due
from jobcaliber.bootstrap import AppContext


class Worker:
    def __init__(self, ctx: AppContext, *, poll_s: float = 30, sleep_fn=time.sleep, now=None,
                 runner=run_once, rebuild=None):
        self.ctx = ctx
        self.poll_s = poll_s
        self.sleep_fn = sleep_fn
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.runner = runner
        self.rebuild = rebuild or self._rebuild
        self._config_mtime = self._mtime()

    def _mtime(self) -> float | None:
        """Newest of the two config files: a change to either must trigger the reload."""
        stamps = []
        for path in (self.ctx.config_path, self.ctx.settings_path):
            try:
                stamps.append(path.stat().st_mtime)
            except OSError:
                pass
        return max(stamps) if stamps else None

    def _rebuild(self, ctx: AppContext) -> AppContext:
        from jobcaliber.bootstrap import build_context

        return build_context(ctx.root, store=ctx.store)

    def refresh(self, *, progress=print) -> AppContext:
        """Cheap per-tick check: a stat() every poll, a full reload only when the file changed."""
        mtime = self._mtime()
        if mtime is not None and mtime != self._config_mtime:
            self.ctx = self.rebuild(self.ctx)
            self._config_mtime = mtime
            progress("config reloaded")
        return self.ctx

    def tick(self, *, progress=print) -> RunOutcome | None:
        """One iteration: recover stale runs, execute a request, or run the schedule."""
        self.refresh(progress=progress)
        store = self.ctx.store
        store.fail_stale_runs()
        config_v, _ = store.config_version(self.ctx.raw_yaml)
        engine = self.ctx.engine

        run_id = store.claim_run(config_v, engine)
        trigger = "manual"
        if run_id is None:
            last = store.last_scheduled_run()
            if not is_due(self.ctx.config.schedule.scrape_times, self.now(),
                          last["started_at"] if last else None, self.ctx.tz):
                return None
            run_id = store.start_run(config_v, engine, "schedule")
            trigger = "schedule"

        outcome = self.runner(self.ctx, trigger=trigger, run_id=run_id, progress=progress)
        if outcome.failed and outcome.retryable and store.requeue(
                run_id, self.ctx.config.schedule.max_attempts
            ):
            progress(f"run {run_id} failed, requeued")
        return outcome

    def run_forever(self, *, progress=print) -> None:
        progress(f"worker started · poll {self.poll_s}s · schedule {self.ctx.config.schedule.scrape_times}")
        while True:
            try:
                self.tick(progress=progress)
            except Exception as error:  # keep the worker alive: the run is already recorded
                progress(f"worker error: {type(error).__name__}: {error}")
            self.sleep_fn(self.poll_s)
