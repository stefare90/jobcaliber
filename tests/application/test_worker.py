from datetime import datetime

from jobcaliber.application.schedule import is_due, last_scheduled_time
from jobcaliber.application.worker import Worker
from jobcaliber.application import runner as runner_module
from jobcaliber.bootstrap import AppContext
from jobcaliber.core.config import AppConfig
from jobcaliber.infrastructure.database import Store
from tests.application.test_runner import FakeFetcher, FakeScorer, posting

YAML = """
search:
  titles: ["Dev"]
  on_site_locations: ["Turin, Italy"]
criteria:
  core_skills:
    min_threshold: 0.5
    apply_threshold: 0.67
    question: {type: "score", instructions: "core?", levels: ["no", "unknown", "partial", "full"], missing: 1}
notifications:
  telegram: {notify_threshold: 70, review_threshold: 60, min_confidence: 0.4}
schedule:
  scrape_times: ["08:00", "13:00"]
  max_attempts: 3
ai:
  engines:
    rizzo: {kind: "decision", api: "systemone", base_url: "http://x", model: "m"}
  roles: {scorer: "rizzo"}
"""


def make_config() -> AppConfig:
    import yaml as pyyaml
    return AppConfig.model_validate(pyyaml.safe_load(YAML))


def make_worker(store, now="2026-10-21T08:05:00", runner=None):
    from pathlib import Path
    config = make_config()
    ctx = AppContext(root=Path("."), config_path=Path("config.yaml"), config=config,
                     raw_yaml=YAML, store=store, engine="rizzo")
    return Worker(ctx, now=lambda: datetime.fromisoformat(now), runner=runner or fake_runner()), ctx


def fake_runner(postings=None, scorer=None):
    def run(ctx, **kwargs):
        kwargs.pop("progress", None)
        return runner_module.run_once(ctx, fetcher=FakeFetcher(postings or [posting(1)]),
                               scorer=scorer or FakeScorer(), progress=lambda *_: None, **kwargs)
    return run


def run_tick(worker, postings=None, scorer=None):
    if postings is not None or scorer is not None:
        worker.runner = fake_runner(postings, scorer)
    return worker.tick(progress=lambda *_: None)


def test_last_scheduled_time_picks_the_most_recent():
    now = datetime(2026, 10, 21, 14, 30)
    assert last_scheduled_time(["08:00", "13:00"], now) == datetime(2026, 10, 21, 13, 0)


def test_last_scheduled_time_rolls_back_before_the_first_slot():
    now = datetime(2026, 10, 21, 6, 0)
    assert last_scheduled_time(["08:00"], now) == datetime(2026, 10, 20, 8, 0)


def test_is_due_without_a_previous_run():
    assert is_due(["08:00"], datetime(2026, 10, 21, 9, 0), None) is True


def test_is_due_after_the_slot_but_not_twice():
    now = datetime(2026, 10, 21, 9, 0)
    assert is_due(["08:00"], now, "2026-10-20 08:00:03") is True
    assert is_due(["08:00"], now, "2026-10-21 08:00:03") is False


def test_is_due_is_false_when_no_time_is_configured():
    assert is_due([], datetime(2026, 10, 21, 9, 0), None) is False


def test_tick_runs_the_schedule_once(tmp_path):
    store = Store(tmp_path / "jobs.db")
    worker, _ = make_worker(store)
    first = run_tick(worker)
    assert first is not None and first.config_v == 1
    second = run_tick(worker)
    assert second is None                      # already ran for this slot
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT trigger, status FROM runs")]
    assert rows == [{"trigger": "schedule", "status": "ok"}]


def test_tick_executes_a_queued_request(tmp_path):
    store = Store(tmp_path / "jobs.db")
    worker, _ = make_worker(store, now="2026-10-21T22:00:00")
    run_id = store.request_run("manual")
    outcome = run_tick(worker)
    assert outcome is not None and outcome.run_id == run_id
    with store.connect() as conn:
        row = dict(conn.execute("SELECT trigger, status, config_v, engine FROM runs WHERE id = ?", (run_id,)).fetchone())
    assert row["trigger"] == "manual" and row["status"] == "ok"
    assert row["config_v"] is not None and row["engine"] == "rizzo"


def test_claim_is_atomic(tmp_path):
    store = Store(tmp_path / "jobs.db")
    run_id = store.request_run("manual")
    assert store.claim_run(1, "rizzo") == run_id
    assert store.claim_run(1, "rizzo") is None


def test_failed_run_is_requeued_up_to_the_limit(tmp_path):
    store = Store(tmp_path / "jobs.db")
    run_id = store.start_run(1, "rizzo", "manual")
    assert store.requeue(run_id, max_attempts=2) is True
    assert store.requeue(run_id, max_attempts=2) is False      # attempt 2 of 2
    with store.connect() as conn:
        row = dict(conn.execute("SELECT status, attempt FROM runs WHERE id = ?", (run_id,)).fetchone())
    assert row == {"status": "requested", "attempt": 2}


def test_failure_in_the_worker_leaves_the_run_failed_after_the_last_attempt(tmp_path):
    store = Store(tmp_path / "jobs.db")
    worker, _ = make_worker(store)

    class Boom:
        def score_posting(self, posting):
            raise RuntimeError("engine down")

    for _ in range(3):
        outcome = run_tick(worker, scorer=Boom())
        assert outcome.failed is True
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT status, attempt FROM runs ORDER BY id")]
    assert rows[-1] == {"status": "failed", "attempt": 3}


def test_config_is_reloaded_when_the_file_changes(tmp_path):
    """A stat() every tick; the file is re-read only when it actually changed."""
    import os
    from jobcaliber.bootstrap import build_context

    root = tmp_path
    (root / "config.yaml").write_text(YAML, encoding="utf-8")
    ctx = build_context(root)
    worker = Worker(ctx, now=lambda: datetime.fromisoformat("2026-10-21T22:00:00"))

    assert worker.refresh(progress=lambda *_: None).config.schedule.scrape_times == ["08:00", "13:00"]

    (root / "config.yaml").write_text(YAML.replace('scrape_times: ["08:00", "13:00"]',
                                                   'scrape_times: ["09:30"]'), encoding="utf-8")
    os.utime(root / "config.yaml", (0, 0))          # force a different mtime
    refreshed = worker.refresh(progress=lambda *_: None)
    assert refreshed.config.schedule.scrape_times == ["09:30"]
    assert refreshed.store is ctx.store             # the database connection is kept


def test_refresh_does_nothing_when_the_config_is_unchanged(tmp_path):
    from jobcaliber.bootstrap import build_context

    (tmp_path / "config.yaml").write_text(YAML, encoding="utf-8")
    ctx = build_context(tmp_path)
    calls = []
    worker = Worker(ctx, now=lambda: datetime.fromisoformat("2026-10-21T22:00:00"),
                    rebuild=lambda current: calls.append(current) or current)
    worker.refresh(progress=lambda *_: None)
    worker.refresh(progress=lambda *_: None)
    assert calls == []
