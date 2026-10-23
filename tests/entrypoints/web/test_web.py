import html as html_lib
import re
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from jobcaliber.core.domain import EvaluationResult, GateDecision, JobPosting, ScoringResult
from jobcaliber.entrypoints.web import create_app
from jobcaliber.infrastructure.config_loader import load_config
from jobcaliber.infrastructure.database import Store
from jobcaliber.bootstrap import AppContext

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def ctx(tmp_path):
    path, config = load_config(ROOT)
    store = Store(tmp_path / "jobs.db")
    return AppContext(root=ROOT, config_path=path, config=config,
                      raw_yaml=path.read_text(encoding="utf-8"), store=store, engine="rizzo",
                      settings_path=path.with_name("settings.yaml"),
                      tz=ZoneInfo(config.schedule.timezone))


@pytest.fixture()
def client(ctx):
    return TestClient(create_app(ctx))


def add_job(store, config_v, external_id, title, company, decision, score, answers, missing=(), run_id=None):
    posting = JobPosting(external_id=external_id, url=external_id, title=title, company=company,
                         source="linkedin", location_raw="Cagliari", description="desc")
    job_id, _ = store.upsert_posting(posting)
    result = ScoringResult(answers=answers, missing=set(missing), confidence=0.9)
    evaluation = EvaluationResult(decision=decision, score_total=score, confidence=0.9,
                                  sub_scores={}, dropped_by=None)
    evaluation_id = store.save_evaluation(job_id, run_id, config_v, "rizzo", result, evaluation)
    return job_id, evaluation_id


def seed(ctx) -> tuple[int, int]:
    """Three offers: one pass, one drop, one review with a missing answer. Returns job/evaluation ids."""
    store = ctx.store
    config_v, _ = store.config_version(ctx.raw_yaml)
    job_id, evaluation_id = add_job(store, config_v, "https://x/1", "Senior Python Developer", "Acme",
                                    GateDecision.PASS, 82.0, {"core_skills": 0.67, "location": "accepted"})
    add_job(store, config_v, "https://x/2", "Java Developer", "Beta",
            GateDecision.DROP, 12.0, {"core_skills": 0.0, "location": "rejected"})
    add_job(store, config_v, "https://x/3", "Embedded Engineer", "Gamma",
            GateDecision.REVIEW, 58.0, {"core_skills": 0.5}, missing={"core_skills"})
    return job_id, evaluation_id


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200 and response.json()["status"] == "ok"


def test_root_redirects_to_the_learning_mode_list(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs?")
    assert "decisions=pass%2Creview" in response.headers["location"]


def test_jobs_without_a_decisions_parameter_shows_every_decision(client, ctx):
    seed(ctx)
    response = client.get("/jobs")
    assert response.status_code == 200
    assert "Senior Python Developer" in response.text
    assert "Embedded Engineer" in response.text
    assert "Java Developer" in response.text               # no parameter = no filter
    assert "core_skills" in response.text                  # dynamic column


def test_the_learning_default_comes_from_the_root_redirect(client, ctx):
    seed(ctx)
    location = client.get("/", follow_redirects=False).headers["location"]
    response = client.get(location)
    assert "decisions=pass%2Creview" in location
    assert "Java Developer" not in response.text


def test_jobs_shows_drops_when_asked(client, ctx):
    seed(ctx)
    response = client.get("/jobs?decisions=pass,review,drop")
    assert "Java Developer" in response.text


def test_jobs_filters_by_text_source_and_criterion(client, ctx):
    seed(ctx)
    assert "Senior Python Developer" in client.get("/jobs?decisions=pass,review,drop&q=python").text
    assert "Beta" not in client.get("/jobs?decisions=pass,review,drop&q=python").text
    filtered = client.get("/jobs?decisions=pass,review,drop&criterion=core_skills&op=le&value=0.5")
    assert "Java Developer" in filtered.text and "Senior Python Developer" not in filtered.text
    only_missing = client.get("/jobs?decisions=pass,review&criterion=core_skills&missing=1")
    assert "Embedded Engineer" in only_missing.text


def test_jobs_rejects_unknown_sort_without_crashing(client, ctx):
    seed(ctx)
    response = client.get("/jobs?sort=score_total;DROP+TABLE+jobs")
    assert response.status_code == 200
    with ctx.store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3


def test_job_detail_shows_answers_and_link(client, ctx):
    job_id, _ = seed(ctx)
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "Senior Python Developer" in response.text
    assert "core_skills" in response.text
    assert "open ↗" in response.text


def test_missing_job_is_404(client):
    assert client.get("/jobs/999").status_code == 404


def test_an_application_is_saved_updated_and_cleared(client, ctx):
    job_id, _ = seed(ctx)
    assert client.post(f"/jobs/{job_id}/application", data={"state": "planned"},
                       follow_redirects=False).status_code == 303
    assert ctx.store.application(job_id).state == "planned"
    client.post(f"/jobs/{job_id}/application", data={"state": "applied"})
    assert ctx.store.application(job_id).state == "applied"
    client.post(f"/jobs/{job_id}/application", data={"state": "none"})
    assert ctx.store.application(job_id) is None


def test_the_application_survives_a_rescore(client, ctx):
    """The mark belongs to the posting, not to the evaluation that was current when it was set."""
    job_id, _ = seed(ctx)
    client.post(f"/jobs/{job_id}/application", data={"state": "applied"})
    config_v, _ = ctx.store.config_version(ctx.raw_yaml)
    add_job(ctx.store, config_v, "https://x/rescore", "Other role", "Acme", GateDecision.PASS, 80.0,
            {"core_skills": 0.9})
    ctx.store.save_evaluation(job_id, None, config_v + 1, "other-engine",
                              ScoringResult(answers={"core_skills": 0.9}), EvaluationResult(
                                  decision=GateDecision.PASS, score_total=90.0, confidence=0.9))
    assert ctx.store.application(job_id).state == "applied"


def test_an_unknown_state_is_rejected(client, ctx):
    job_id, _ = seed(ctx)
    assert client.post(f"/jobs/{job_id}/application", data={"state": "meh"}).status_code == 400


def test_the_applications_page_lists_what_was_marked(client, ctx):
    job_id, _ = seed(ctx)
    client.post(f"/jobs/{job_id}/application", data={"state": "applied"})
    page = client.get("/applications").text
    assert "Applications" in page and "applied" in page
    csv_text = client.get("/applications.csv").text
    assert csv_text.splitlines()[0].startswith("state,")
    assert "applied" in csv_text


def test_the_list_filters_by_state_and_shows_the_status_column(client, ctx):
    job_id, _ = seed(ctx)
    client.post(f"/jobs/{job_id}/application", data={"state": "planned"})
    assert ">planned<" in client.get("/jobs?cols=status&state=planned").text
    assert "No results" in client.get("/jobs?cols=status&state=applied").text


def test_run_request_goes_through_the_queue(client, ctx):
    response = client.post("/run", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/runs"
    assert ctx.store.pending_requests() == 1
    with ctx.store.connect() as conn:
        row = conn.execute("SELECT trigger, status FROM runs").fetchone()
    assert (row["trigger"], row["status"]) == ("manual", "requested")


def test_runs_page_lists_the_queue(client, ctx):
    client.post("/run")
    response = client.get("/runs")
    assert response.status_code == 200 and "requested" in response.text


ALLOWED_STORE_METHODS = {
    "jobs", "count_jobs", "job", "latest_evaluation", "answers_for", "missing_for",
    "application", "applications", "applications_for",
    "criterion_columns", "runs", "last_run", "last_completed_run", "pending_requests",
    "save_application", "clear_application", "request_run",
}


def test_the_web_only_writes_applications_and_run_requests():
    """The web may mark a posting and queue a run. Everything else it only reads."""
    import re

    web = Path(__file__).resolve().parents[3] / "src" / "jobcaliber" / "entrypoints" / "web"
    called = set()
    for path in web.rglob("*.py"):
        called |= set(re.findall(r"store\.(\w+)\(", path.read_text(encoding="utf-8")))
    assert called <= ALLOWED_STORE_METHODS, f"unexpected Store calls from the web: {called - ALLOWED_STORE_METHODS}"
    assert {"save_application", "clear_application", "request_run"} <= called


def test_choice_criterion_filters_by_option(client, ctx):
    seed(ctx)
    response = client.get("/jobs?decisions=pass,review,drop&criterion=location&value=accepted")
    assert "Senior Python Developer" in response.text
    assert "Java Developer" not in response.text


def test_the_default_scope_is_all_offers(client, ctx):
    seed(ctx)
    response = client.get("/jobs?decisions=pass,review")
    assert "2 offers" in response.text         # pass + review, from every run
    assert "every run" in response.text        # the run filter lists runs by date


def test_last_scope_uses_the_last_completed_run_and_falls_back(client, ctx):
    seed(ctx)
    ctx.store.request_run("manual")             # a pending request must not blank the list
    response = client.get("/jobs?run=last&decisions=pass,review")
    assert response.status_code == 200
    assert "2 offers" in response.text         # no completed run: fall back to everything


def test_pagination_keeps_the_filters(client, ctx):
    store = ctx.store
    config_v, _ = store.config_version(ctx.raw_yaml)
    for index in range(12):
        add_job(store, config_v, f"https://x/p{index}", f"Python dev {index}", "Acme",
                GateDecision.PASS, 50.0 + index, {"core_skills": 0.67})
    page1 = client.get("/jobs?decisions=pass&limit=10&offset=0")
    assert "next ›" in page1.text
    assert "decisions=pass" in page1.text and "limit=10" in page1.text
    page2 = client.get("/jobs?decisions=pass&limit=10&offset=10")
    assert page2.status_code == 200
    titles1 = {line for line in page1.text.splitlines() if "Python dev" in line}
    titles2 = {line for line in page2.text.splitlines() if "Python dev" in line}
    assert titles1 and titles2 and not (titles1 & titles2)


def test_an_offset_past_the_last_page_clamps_instead_of_showing_nothing(client, ctx):
    seed(ctx)
    response = client.get("/jobs?run=all&decisions=pass,review,drop&limit=10&offset=500")
    assert response.status_code == 200
    assert "2 offers" in response.text or "3 offers" in response.text
    assert "No results" not in response.text


def test_pager_links_keep_every_filter(client, ctx):
    store = ctx.store
    config_v, _ = store.config_version(ctx.raw_yaml)
    for index in range(15):
        add_job(store, config_v, f"https://x/loc{index}", f"Rejected role {index}", "Acme",
                GateDecision.REVIEW, 40.0 + index, {"location": "rejected"})
    page = client.get("/jobs?run=all&criterion=location&value=rejected&limit=10&offset=0")
    assert "next ›" in page.text
    href = page.text.split('class="pager"')[1].split('href="')[1].split('"')[0]
    for fragment in ("criterion=location", "value=rejected", "limit=10", "offset=10", "run=all"):
        assert fragment in href, f"{fragment} missing from {href}"


def test_every_decision_is_an_explicit_state(client, ctx):
    """Regression: "all decisions" used to be an absent parameter, which the form rendered as
    nothing checked. It is now explicit, so the checkboxes always match what is listed."""
    store = ctx.store
    config_v, _ = store.config_version(ctx.raw_yaml)
    for index in range(15):
        add_job(store, config_v, f"https://x/pg{index}", f"Role {index}", "Acme",
                GateDecision.DROP, 10.0 + index, {"core_skills": 0.0})
    page = client.get("/jobs?limit=10")
    assert page.text.split('<p class="count">')[1].split(' ')[0] == "15"
    href = page.text.split('class="pager"')[1].split('href="')[1].split('"')[0]
    assert "decisions=pass%2Creview%2Cdrop" in href      # explicit, so it cannot drift
    page2 = client.get("/jobs?limit=10&offset=10")
    assert page2.text.split('<p class="count">')[1].split(' ')[0] == "15"


def test_decisions_accept_both_form_style_and_comma_style(client, ctx):
    seed(ctx)
    form_style = client.get("/jobs?decisions=pass&decisions=review&decisions=drop")
    comma_style = client.get("/jobs?decisions=pass,review,drop")
    assert "3 offers" in form_style.text and "3 offers" in comma_style.text
    checked = re.findall(r'value="(pass|review|drop)"\s*\n?\s*checked', form_style.text)
    assert sorted(checked) == ["drop", "pass", "review"]
    only_review = client.get("/jobs?decisions=review")
    assert "1 offers" in only_review.text


def test_reset_returns_to_the_initial_state(client, ctx):
    """Reset must land on the same state as the first visit: pass+review, every run."""
    seed(ctx)
    page = client.get("/jobs?decisions=pass,review,drop&criterion=location&value=rejected&q=zzz")
    assert 'href="/">Reset</a>' in page.text
    reset = client.get("/", follow_redirects=True)
    assert "2 offers" in reset.text                       # pass + review only
    assert "every run" in reset.text


def test_run_filter_lists_runs_and_filters_by_id(client, ctx):
    seed(ctx)
    run_id = ctx.store.start_run(1, "rizzo", "manual")
    page = client.get(f"/jobs?run={run_id}")
    assert page.status_code == 200
    assert f'value="{run_id}"' in page.text               # the run appears in the select
    assert "0 offers" in page.text                        # no evaluation belongs to it yet


def test_exclude_missing_hides_unjudgeable_offers(client, ctx):
    seed(ctx)
    everything = client.get("/jobs?decisions=pass,review,drop")
    without_missing = client.get("/jobs?decisions=pass,review,drop&exclude_missing=1")
    assert "3 offers" in everything.text
    assert "2 offers" in without_missing.text             # the "cannot tell" one is hidden
    assert "Embedded Engineer" not in without_missing.text


def test_run_column_is_sortable_when_visible(client, ctx):
    seed(ctx)
    hidden = client.get("/jobs?sort=run_started_at&dir=desc")
    assert hidden.status_code == 200 and "Run</a>" not in hidden.text   # off by default
    shown = client.get("/jobs?cols=core_skills,run&sort=run_started_at&dir=desc")
    assert "Run</a>" in shown.text


def test_templates_escape_scraped_content(client, ctx):
    """Titles come from boards: a `<script>` in one must never reach the browser as markup."""
    store = ctx.store
    config_v, _ = store.config_version(ctx.raw_yaml)
    add_job(store, config_v, "https://x/xss", '<script>alert("x")</script>', "Evil & Co",
            GateDecision.PASS, 90.0, {"core_skills": 0.67})
    page = client.get("/jobs?decisions=pass")
    assert "<script>" not in page.text
    assert "&lt;script&gt;" in page.text
    assert "Evil &amp; Co" in page.text


def test_columns_can_be_selected_from_the_form(client, ctx):
    seed(ctx)
    page = client.get("/jobs?cols=core_skills")
    assert 'name="cols" value="core_skills"' in page.text
    assert "cols=core_skills" in page.text
    assert ">core_skills</a></th>" in page.text
    assert ">location</a></th>" not in page.text          # the other criterion columns are hidden
    everything = client.get("/jobs?cols=core_skills,location")
    assert ">location</a></th>" in everything.text


def test_salary_is_not_a_table_column_but_stays_on_the_detail(client, ctx):
    seed(ctx)
    page = client.get("/jobs")
    assert "<th>Salary</th>" not in page.text
    job_id = page.text.split('/jobs/')[1].split('"')[0]
    assert "Salary" in client.get(f"/jobs/{job_id}").text


def test_every_criterion_is_a_default_column(client, ctx):
    job_id, _ = seed(ctx)
    config_v, _ = ctx.store.config_version(ctx.raw_yaml)
    add_job(ctx.store, config_v, "https://x/gate", "Gated role", "Acme", GateDecision.PASS, 75.0,
            {"core_skills": 0.67, "applicable": "no"})
    text = client.get("/jobs").text
    assert ">core_skills</a></th>" in text
    assert ">applicable</a></th>" in text           # gates are columns too, no in_table flag
    narrowed = client.get("/jobs?cols=core_skills")
    assert ">applicable</a></th>" not in narrowed.text


def test_description_blank_lines_are_collapsed(client, ctx):
    from jobcaliber.entrypoints.web.readmodels import normalize_description

    assert normalize_description("a\n\n\n\nb\n\n\nc") == "a\n\nb\n\nc"
    assert normalize_description("  a\r\n\r\n\r\n  b  ") == "a\n\n  b"
    assert normalize_description(None) == ""
    assert normalize_description("a\n\nb") == "a\n\nb"      # exactly two lines stay untouched


def test_the_filter_panel_is_closed_by_default(client, ctx):
    seed(ctx)
    page = client.get("/jobs")
    assert '<details class="filters">' in page.text
    assert '<details class="filters" open>' not in page.text
    assert "Filters" in page.text


def test_every_configured_criterion_is_filterable(client, ctx):
    """Criteria come from the config, so a new one is filterable before it has any answer."""
    criterion = "brand_new"
    ctx.config.criteria[criterion] = ctx.config.criteria["core_skills"].model_copy()
    page = client.get("/jobs")
    assert f'name="criterion"' in page.text
    assert f'<option value="{criterion}"' in page.text
    assert f'name="cols" value="{criterion}"' in page.text


def test_value_field_shows_the_options_of_the_selected_criterion(client, ctx):
    seed(ctx)
    choice = client.get("/jobs?criterion=location&value=accepted")
    assert '<select name="value"' in choice.text
    options = re.findall(r'<option value="(\w+)"[^>]*>\1</option>', choice.text)
    assert "accepted" in options and "yes" not in options      # only this criterion's options
    score = client.get("/jobs?criterion=core_skills&op=ge&value=0.5")
    assert '<input type="text" name="value"' in score.text
    assert '<select name="value"' not in score.text
    empty = client.get("/jobs")
    assert '<input type="text" name="value"' in empty.text     # always visible


def test_description_is_rendered_as_markdown_but_raw_html_is_escaped(client, ctx):
    from jobcaliber.entrypoints.web.readmodels import render_markdown

    html = render_markdown("**Senior** role\n\n* C++\n* Python\n\n<script>alert(1)</script>")
    assert "<strong>Senior</strong>" in html
    assert "<ul>" in html and "<li>C++</li>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html

    store = ctx.store
    config_v, _ = store.config_version(ctx.raw_yaml)
    posting = JobPosting(external_id="https://x/md", url="https://x/md", title="MD role",
                        company="Acme", source="linkedin",
                        description="**Firmware** engineer\n\n* C++\n* RTOS")
    job_id, _ = store.upsert_posting(posting)
    store.save_evaluation(job_id, None, config_v, "rizzo", ScoringResult(answers={"core_skills": 0.67}),
                          EvaluationResult(decision=GateDecision.PASS, score_total=80, confidence=0.9))
    page = client.get(f"/jobs/{job_id}")
    assert "<strong>Firmware</strong>" in page.text
    assert "<li>RTOS</li>" in page.text
    assert '<pre class="description">' not in page.text


def test_the_nav_link_keeps_the_active_filters(client, ctx):
    seed(ctx)
    page = client.get("/jobs?decisions=pass&criterion=core_skills&op=ge&value=0.5")
    nav = page.text.split('<nav>')[1].split('</nav>')[0]
    href = html_lib.unescape(nav.split('href="')[1].split('"')[0])
    assert "decisions=pass" in href and "criterion=core_skills" in href
    assert "value=0.5" in href


def test_the_nav_link_from_the_detail_page_keeps_the_filters(client, ctx):
    job_id, _ = seed(ctx)
    page = client.get(f"/jobs/{job_id}?decisions=pass&q=python")
    nav = page.text.split('<nav>')[1].split('</nav>')[0]
    href = html_lib.unescape(nav.split('href="')[1].split('"')[0])
    assert "decisions=pass" in href and "q=python" in href


def test_the_nav_falls_back_to_the_default_list_without_filters(client, ctx):
    seed(ctx)
    nav = client.get("/runs").text.split('<nav>')[1].split('</nav>')[0]
    assert 'href="/"' in nav


def test_the_detail_link_carries_the_list_filters(client, ctx):
    seed(ctx)
    page = client.get("/jobs?decisions=pass&criterion=core_skills&op=ge&value=0.5&offset=10&limit=10")
    href = html_lib.unescape(page.text.split('<td><a href="')[1].split('"')[0])
    assert href.startswith("/jobs/")
    assert "decisions=pass" in href and "criterion=core_skills" in href
    assert "offset=10" in href and "limit=10" in href


def test_back_from_the_detail_returns_to_the_same_page_and_filters(client, ctx):
    store = ctx.store
    config_v, _ = store.config_version(ctx.raw_yaml)
    for index in range(15):
        add_job(store, config_v, f"https://x/back{index}", f"Backend role {index}", "Acme",
                GateDecision.PASS, 60.0 + index, {"core_skills": 0.67})
    listing = client.get("/jobs?decisions=pass&limit=10&offset=10")
    assert "11–" in listing.text                       # page 2
    detail_href = html_lib.unescape(listing.text.split('<td><a href="')[1].split('"')[0])
    detail = client.get(detail_href)
    nav_href = html_lib.unescape(detail.text.split("<nav>")[1].split('href="')[1].split('"')[0])
    assert "offset=10" in nav_href and "decisions=pass" in nav_href
    back = client.get(nav_href)
    assert "11–" in back.text                          # still page 2


def test_runs_show_local_time(client, ctx):
    from jobcaliber.core.formatting import local_time

    store = ctx.store
    run_id = store.start_run(1, "rizzo", "manual")
    with store.connect() as conn:
        conn.execute("UPDATE runs SET started_at = '2026-10-23 08:00:00', status = 'ok' WHERE id = ?",
                     (run_id,))
    page = client.get("/runs").text
    assert local_time("2026-10-23 08:00:00", ctx.tz) in page
    assert "2026-10-23 08:00" not in page
