import pytest
from zoneinfo import ZoneInfo

from jobcaliber.application.runner import run_once
from jobcaliber.bootstrap import AppContext
from jobcaliber.core.config import AppConfig
from jobcaliber.core.domain import EvaluationResult, GateDecision, JobPosting, ScoringResult
from jobcaliber.infrastructure.database import Store

YAML = """
search:
  titles: ["Dev"]
  on_site_locations: ["Turin, Italy"]
schedule:
  timezone: "Europe/Rome"
criteria:
  core_skills:
    min_threshold: 0.5
    apply_threshold: 0.67
    question: {type: "score", instructions: "core?", levels: ["no", "unknown", "partial", "full"], missing: 1}
  location:
    gate: {accept: ["accepted"]}
    question:
      type: "choice"
      instructions: "where?"
      options: {accepted: "in", rejected: "out", unknown: "unknown"}
      missing: "unknown"
notifications:
  telegram: {notify_threshold: 70, review_threshold: 60, min_confidence: 0.4}
ai:
  engines:
    rizzo: {kind: "decision", api: "systemone", base_url: "http://x", model: "m"}
  roles: {scorer: "rizzo"}
"""


def make_config() -> AppConfig:
    import yaml as pyyaml
    return AppConfig.model_validate(pyyaml.safe_load(YAML))


class FakeQuery:
    def __init__(self, keywords="Dev", location="Turin, Italy", remote=False):
        self.keywords, self.location, self.role, self.remote = keywords, location, keywords, remote


class FakeFetcher:
    def __init__(self, postings):
        self.postings = postings
        self.boards = ["linkedin"]
        self.calls = 0

    def build_queries(self):
        return [FakeQuery()]

    def fetch_board(self, query, board):
        self.calls += 1
        stats = type("S", (), {"seen": len(self.postings), "usable": len(self.postings), "new": 0, "errors": []})()
        return list(self.postings), stats


class FakeScorer:
    def __init__(self, answers=None, probe_error=None):
        self.answers = answers or {"core_skills": 1.0, "location": "accepted"}
        self.calls = 0
        self.probed = 0
        self.probe_error = probe_error

    def probe(self):
        self.probed += 1
        if self.probe_error:
            raise self.probe_error

    def score_posting(self, posting):
        self.calls += 1
        return ScoringResult(answers=dict(self.answers), missing=set(), confidence=0.9)


def posting(n: int) -> JobPosting:
    return JobPosting(external_id=f"https://x/{n}", url=f"https://x/{n}", title=f"Dev {n}",
                      company="Acme", source="linkedin", location_raw="Turin, Italy")


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "jobs.db")


def context(config, store, yaml_text=YAML, engine="rizzo") -> AppContext:
    return AppContext(root=Path("."), config_path=Path("config.yaml"), config=config,
                      raw_yaml=yaml_text, store=store, engine=engine,
                      settings_path=Path("settings.yaml"), tz=ZoneInfo(config.schedule.timezone))


def run(config, store, postings, scorer=None, yaml_text=YAML, engine="rizzo", fetcher=None, **kw):
    return run_once(context(config, store, yaml_text, engine),
                    fetcher=fetcher or FakeFetcher(postings), scorer=scorer or FakeScorer(),
                    progress=lambda *_: None, **kw)


from pathlib import Path  # noqa: E402  (used by run())


def test_first_run_scores_and_persists(store):
    outcome = run(make_config(), store, [posting(1), posting(2)])
    assert (outcome.fetched, outcome.new, outcome.scored) == (2, 2, 2)
    assert outcome.decisions["pass"] == 2
    assert store.last_run()["status"] == "ok"
    assert len(store.jobs()) == 2


def test_second_run_scores_nothing_with_the_same_config(store):
    config = make_config()
    run(config, store, [posting(1), posting(2)])
    scorer = FakeScorer()
    outcome = run(config, store, [posting(1), posting(2)], scorer=scorer)
    assert outcome.scored == 0
    assert outcome.new == 0          # the same postings, already known
    assert scorer.calls == 0
    assert len(store.jobs()) == 2


def test_changed_config_rescores_everything(store):
    config = make_config()
    run(config, store, [posting(1)])
    outcome = run(config, store, [posting(1)], yaml_text=YAML + "\n# changed\n")
    assert outcome.config_v == 2
    assert outcome.scored == 1


def test_new_engine_rescores_everything(store):
    config = make_config()
    run(config, store, [posting(1)])
    outcome = run(config, store, [posting(1)], engine="rizzo", yaml_text=YAML)
    assert outcome.scored == 0          # same engine: nothing pending
    config.ai.engines["other"] = config.ai.engines["rizzo"].model_copy()
    outcome = run(config, store, [posting(1)], engine="other")
    assert outcome.scored == 1


def test_limit_caps_the_number_of_scored_postings(store):
    config = make_config()
    outcome = run(config, store, [posting(1), posting(2), posting(3)], limit=2)
    assert outcome.scored == 2
    assert len(store.pending(outcome.config_v, "rizzo")) == 1


def test_dry_run_writes_nothing(store):
    config = make_config()
    outcome = run(config, store, [posting(1)], dry_run=True)
    assert outcome.dry_run is True and outcome.scored == 1 and outcome.run_id is None
    assert store.last_run() is None
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 0


def test_dropped_postings_are_stored_with_the_gate_name(store):
    config = make_config()
    run(config, store, [posting(1)], scorer=FakeScorer({"core_skills": 1.0, "location": "rejected"}))
    rows = store.jobs(decisions=["drop"])
    assert len(rows) == 1 and rows[0].dropped_by == "location"


def test_failure_is_recorded_and_reported(store):
    config = make_config()

    class Boom:
        def probe(self):
            pass

        def score_posting(self, posting):
            raise RuntimeError("engine down")

    outcome = run(config, store, [posting(1)], scorer=Boom())
    assert outcome.failed is True and "engine down" in outcome.error
    last = store.last_run()
    assert last["status"] == "failed" and "engine down" in last["error"]


def test_probe_fails_fast_before_the_fetch(store, monkeypatch):
    """An engine that is down must not cost the fetch: nothing is collected."""
    from jobcaliber.infrastructure.ai.client.base import EngineUnreachable

    config = make_config()
    fetcher = FakeFetcher([posting(1)])
    scorer = FakeScorer(probe_error=EngineUnreachable("engine unreachable at 127.0.0.1:8017"))
    outcome = run(config, store, [posting(1)], scorer=scorer, fetcher=fetcher)
    assert outcome.failed is True and "unreachable" in outcome.error
    assert outcome.retryable is False
    assert fetcher.calls == 0 and scorer.calls == 0
    assert store.last_run()["status"] == "failed"


def test_a_scoring_error_stays_retryable(store):
    class Boom:
        def probe(self):
            pass

        def score_posting(self, posting):
            raise RuntimeError("engine down")

    outcome = run(make_config(), store, [posting(1)], scorer=Boom())
    assert outcome.failed is True and outcome.retryable is True


def test_postings_are_persisted_board_by_board(store):
    """A run that dies mid-fetch must not lose what it already collected."""
    config = make_config()

    class ProbeFetcher(FakeFetcher):
        def __init__(self, postings, boards, check):
            super().__init__(postings)
            self.boards = boards
            self.check = check

        def fetch_board(self, query, board):
            self.check(board)
            return super().fetch_board(query, board)

    seen = {}

    def check(board):
        with store.connect() as conn:
            seen[board] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    fetcher = ProbeFetcher([posting(1), posting(2)], ["linkedin", "indeed"], check)
    run(config, store, [posting(1), posting(2)], fetcher=fetcher)
    assert seen["linkedin"] == 0                      # nothing before the first board
    assert seen["indeed"] == 2                        # the first board was already stored


class FakeNotifier:
    def __init__(self, error=None):
        self.error = error
        self.rows = []
        self.run_id = None

    def send(self, rows, run_id):
        self.rows = list(rows)
        self.run_id = run_id
        return self.error


def test_a_successful_run_notifies_the_pass_postings(store):
    notifier = FakeNotifier()
    outcome = run(make_config(), store, [posting(1), posting(2)], notifier=notifier)
    assert outcome.failed is False
    assert len(notifier.rows) == 2 and notifier.run_id == outcome.run_id
    assert all(row.decision == "pass" for row in notifier.rows)
    with store.connect() as conn:
        notified = conn.execute("SELECT COUNT(*) FROM jobs WHERE notified_at IS NOT NULL").fetchone()[0]
    assert notified == 2


def test_review_postings_are_not_notified(store):
    notifier = FakeNotifier()
    scorer = FakeScorer({"core_skills": 0.55, "location": "accepted"})   # below apply_threshold
    run(make_config(), store, [posting(1)], scorer=scorer, notifier=notifier)
    assert notifier.rows == []


def test_a_delivery_failure_keeps_the_run_ok_and_the_offer_unnotified(store):
    notifier = FakeNotifier(error="400: chat not found")
    outcome = run(make_config(), store, [posting(1)], notifier=notifier)
    assert outcome.failed is False and store.last_run()["status"] == "ok"
    with store.connect() as conn:
        notified = conn.execute("SELECT COUNT(*) FROM jobs WHERE notified_at IS NOT NULL").fetchone()[0]
    assert notified == 0


def test_a_marked_posting_is_not_notified(store):
    """If the user already applied to (or dismissed) an offer, Telegram must not bring it back."""
    notifier = FakeNotifier()
    config = make_config()
    first = run(config, store, [posting(1)], notifier=FakeNotifier())
    assert first.decisions["pass"] == 1
    job_id = store.jobs(decisions=["pass"])[0].id
    store.save_application(job_id, "applied")

    second = run(config, store, [posting(1)], engine="other", notifier=notifier)
    assert second.decisions["pass"] == 1          # scored again for the new engine
    assert notifier.rows == []                    # but not notified
