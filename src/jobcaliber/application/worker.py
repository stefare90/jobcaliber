"""The worker: owns the schedule, claims queued runs, executes them one at a time."""
from __future__ import annotations

import time
from datetime import datetime

from jobcaliber.application.runner import RunOutcome, run_once
from jobcaliber.application.schedule import is_due
from jobcaliber.bootstrap import AppContext


class Worker:
    def __init__(self, ctx: AppContext, *, poll_s: float = 30, sleep_fn=time.sleep, now=None,
                 runner=run_once):
        self.ctx = ctx
        self.poll_s = poll_s
        self.sleep_fn = sleep_fn
        self.now = now or datetime.now
        self.runner = runner

    def tick(self, *, progress=print) -> RunOutcome | None:
        """One iteration: recover stale runs, execute a request, or run the schedule."""
        store = self.ctx.store
        store.fail_stale_runs()
        config_v, _ = store.config_version(self.ctx.raw_yaml)
        engine = self.ctx.engine

        run_id = store.claim_run(config_v, engine)
        trigger = "manual"
        if run_id is None:
            last = store.last_scheduled_run()
            if not is_due(self.ctx.config.schedule.scrape_times, self.now(),
                          last["started_at"] if last else None):
                return None
            run_id = store.start_run(config_v, engine, "schedule")
            trigger = "schedule"

        outcome = self.runner(self.ctx, trigger=trigger, run_id=run_id, progress=progress)
        if outcome.failed and store.requeue(run_id, self.ctx.config.schedule.max_attempts):
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
