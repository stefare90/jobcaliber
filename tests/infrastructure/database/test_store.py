import pytest

from jobcaliber.core.domain import EvaluationResult, GateDecision, JobPosting, ScoringResult
from jobcaliber.infrastructure.database import Filter, RunStats, Store


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "jobs.db")


def posting(external_id="https://x/1", title="Dev", company="Acme", **over):
    return JobPosting(external_id=external_id, url=external_id, title=title, company=company,
                      source=over.pop("source", "linkedin"),
                      location_raw=over.pop("location_raw", "Cagliari"),
                      description=over.pop("description", "desc"),
                      query_term=over.pop("query_term", "Dev"),
                      query_location=over.pop("query_location", "Sardinia, Italy"), **over)


def scored(**answers):
    return ScoringResult(answers=answers or {"core_skills": 0.67, "location": "accepted"},
                         missing=set(), confidence=0.9)


def evaluated(decision=GateDecision.PASS, dropped_by=None, score=80.0):
    return EvaluationResult(decision=decision, score_total=score, confidence=0.9,
                            sub_scores={"core_skills": 0.67}, dropped_by=dropped_by)


def test_upsert_is_idempotent(store):
    job_id, is_new = store.upsert_posting(posting())
    again_id, again_new = store.upsert_posting(posting())
    assert (job_id, is_new) == (again_id, True)
    assert again_new is False
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_upsert_refreshes_last_seen(store):
    job_id, _ = store.upsert_posting(posting())
    with store.connect() as conn:
        first = conn.execute("SELECT last_seen_at FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    store.upsert_posting(posting(description="updated description"))
    with store.connect() as conn:
        row = conn.execute("SELECT description, last_seen_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["description"] == "updated description"
    assert row["last_seen_at"] >= first


def test_pending_excludes_evaluated_postings(store):
    v, _ = store.config_version("cfg")
    first, _ = store.upsert_posting(posting("https://x/1"))
    store.upsert_posting(posting("https://x/2"))
    store.save_evaluation(first, None, v, "rizzo", scored(), evaluated())
    pending = store.pending(v, "rizzo")
    assert [p.external_id for p in pending] == ["https://x/2"]


def test_pending_returns_everything_for_a_new_config(store):
    v1, _ = store.config_version("cfg1")
    v2, _ = store.config_version("cfg2")
    job_id, _ = store.upsert_posting(posting())
    store.save_evaluation(job_id, None, v1, "rizzo", scored(), evaluated())
    assert store.pending(v1, "rizzo") == []
    assert len(store.pending(v2, "rizzo")) == 1


def test_pending_returns_everything_for_a_new_engine(store):
    v, _ = store.config_version("cfg")
    job_id, _ = store.upsert_posting(posting())
    store.save_evaluation(job_id, None, v, "rizzo", scored(), evaluated())
    assert store.pending(v, "rizzo") == []
    assert len(store.pending(v, "jev")) == 1


def test_same_evaluation_twice_creates_one_row(store):
    v, _ = store.config_version("cfg")
    job_id, _ = store.upsert_posting(posting())
    first = store.save_evaluation(job_id, None, v, "rizzo", scored(), evaluated())
    second = store.save_evaluation(job_id, None, v, "rizzo", scored(), evaluated(score=10.0))
    assert first == second
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 1


def test_answers_are_normalised(store):
    v, _ = store.config_version("cfg")
    job_id, _ = store.upsert_posting(posting())
    result = ScoringResult(answers={"core_skills": 0.67, "location": "accepted", "pay": 0.5},
                           missing={"pay"}, confidence=0.9)
    evaluation_id = store.save_evaluation(job_id, None, v, "rizzo", result, evaluated())
    stored = store.evaluation(evaluation_id)
    assert stored["answers"] == {"core_skills": 0.67, "location": "accepted", "pay": 0.5}
    assert stored["missing"] == ["pay"]
    assert stored["dropped_by"] is None


def test_an_application_is_one_updatable_row_per_job(store):
    job_id, _ = store.upsert_posting(posting())
    store.save_application(job_id, "planned")
    assert store.application(job_id).state == "planned"
    store.save_application(job_id, "applied")
    assert store.application(job_id).state == "applied"
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    assert store.applied_job_ids() == {job_id}
    store.clear_application(job_id)
    assert store.application(job_id) is None and store.applied_job_ids() == set()


def test_unknown_application_state_is_rejected(store):
    job_id, _ = store.upsert_posting(posting())
    with pytest.raises(ValueError, match="state must be one of"):
        store.save_application(job_id, "maybe")


def test_config_version_is_content_addressed(store):
    v1, sha1 = store.config_version("a: 1")
    assert (v1, sha1) == store.config_version("a: 1")
    v2, sha2 = store.config_version("b: 2")
    assert v2 != v1 and sha2 != sha1
    assert store.config_yaml(v1) == "a: 1"
    assert len(sha1) == 16 and sha1 == store.config_version("a: 1")[1]


def test_new_notifiable_only_uses_the_latest_evaluation(store):
    v, _ = store.config_version("cfg")
    job_id, _ = store.upsert_posting(posting())
    store.save_evaluation(job_id, None, v, "rizzo", scored(),
                          evaluated(GateDecision.DROP, dropped_by="location", score=0.0))
    v2, _ = store.config_version("cfg2")
    store.save_evaluation(job_id, None, v2, "rizzo", scored(), evaluated(GateDecision.REVIEW, score=55.0))
    notifiable = store.new_notifiable()
    assert [row.decision for row in notifiable] == ["review"]


def test_new_notifiable_carries_the_run_the_evaluation_belongs_to(store):
    v, _ = store.config_version("cfg")
    job_id, _ = store.upsert_posting(posting())
    run_id = store.start_run(v, "rizzo", "schedule")
    store.save_evaluation(job_id, run_id, v, "rizzo", scored(), evaluated(GateDecision.REVIEW))
    assert [row.run_id for row in store.new_notifiable()] == [run_id]


def test_mark_notified_is_idempotent(store):
    v, _ = store.config_version("cfg")
    job_id, _ = store.upsert_posting(posting())
    store.save_evaluation(job_id, None, v, "rizzo", scored(), evaluated())
    assert len(store.new_notifiable()) == 1
    store.mark_notified([job_id])
    with store.connect() as conn:
        first = conn.execute("SELECT notified_at FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    store.mark_notified([job_id])
    with store.connect() as conn:
        second = conn.execute("SELECT notified_at FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    assert first == second
    assert store.new_notifiable() == []


def test_jobs_filter_and_sort(store):
    v, _ = store.config_version("cfg")
    a, _ = store.upsert_posting(posting("https://x/a", title="Python Dev"))
    b, _ = store.upsert_posting(posting("https://x/b", title="Java Dev", source="indeed"))
    store.save_evaluation(a, None, v, "rizzo", scored(), evaluated(GateDecision.PASS, score=90.0))
    store.save_evaluation(b, None, v, "rizzo", scored(), evaluated(GateDecision.DROP, dropped_by="core_skills", score=10.0))

    assert [row.id for row in store.jobs(sort="score_total")] == [a, b]
    assert [row.id for row in store.jobs(sort="score_total", direction="asc")] == [b, a]
    assert [row.id for row in store.jobs(decisions=["drop"])] == [b]
    assert [row.id for row in store.jobs(filters=[Filter("board", "is", value=("indeed",))])] == [b]
    assert [row.id for row in store.jobs(text="python")] == [a]
    with pytest.raises(ValueError, match="cannot sort by"):
        store.jobs(sort="drop; DROP TABLE jobs")


def test_run_lifecycle(store):
    v, _ = store.config_version("cfg")
    run_id = store.start_run(v, "rizzo", "manual")
    assert store.run(run_id)["status"] == "running"
    store.finish_run(run_id, RunStats(fetched=10, usable=8, new=3, scored=3), duration_ms=1234)
    row = store.last_run()
    assert row["id"] == run_id and row["status"] == "ok"
    assert (row["fetched"], row["new"], row["scored"], row["duration_ms"]) == (10, 3, 3, 1234)


def test_schema_can_be_applied_twice(tmp_path):
    path = tmp_path / "jobs.db"
    Store(path)
    Store(path)
    store = Store(path)
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_the_profile_keys_evaluations_and_the_settings_do_not(tmp_path):
    """The version is the profile content (plus the rubric version), never the runtime settings."""
    import jobcaliber.infrastructure.database.store as store_module

    store = Store(tmp_path / "jobs.db")
    profile = "search: {titles: [Dev]}\ncriteria: {core: {min_threshold: 0.5}}\n"
    first, _ = store.config_version(profile)
    assert store.config_version(profile)[0] == first          # same content, same version
    assert store.config_version(profile + "\n# edited\n")[0] == first + 1

    original = store_module.RUBRIC_VERSION
    store_module.RUBRIC_VERSION = original + 1
    try:
        assert store.config_version(profile)[0] == first + 2     # new rubric -> new version
    finally:
        store_module.RUBRIC_VERSION = original
