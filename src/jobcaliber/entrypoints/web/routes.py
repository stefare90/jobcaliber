"""HTTP surface: parse the query string, ask the read models, render. No business logic."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from jobcaliber.bootstrap import AppContext
from jobcaliber.entrypoints.web.readmodels import job_detail, job_table

DECISIONS = ("pass", "review", "drop")
DEFAULT_DECISIONS = ("pass", "review")
OPTIONAL_COLUMNS = ("salary", "last_seen", "run", "feedback")
OPERATORS = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥", "eq": "="}
SORTS = ("score_total", "confidence", "decision", "title", "company", "source",
         "first_seen_at", "last_seen_at", "run_started_at")
HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parents[3]


def default_filters() -> dict:
    return {
        "decisions": list(DEFAULT_DECISIONS), "source": None, "text": None, "criterion": None,
        "op": None, "value": None, "option": None, "criterion_type": None,
        "exclude_missing": False, "run": "all", "run_id": None,
        "columns": set(), "selectable_columns": [], "criterion_columns": [], "criterion_names": [],
        "sort": "score_total", "dir": "desc", "limit": 50, "offset": 0,
    }


def _float(raw: str | None, low: float, high: float) -> float | None:
    try:
        return max(low, min(high, float(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(raw: str | None, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def parse_filters(request: Request, ctx: AppContext) -> dict:
    """Validate every query parameter: nothing from the URL reaches SQL unchecked."""
    params = request.query_params
    # The form sends one key per checkbox (`decisions=pass&decisions=review`), the pager link
    # sends them comma-separated; both must work. The state is always explicit: no key means
    # "every decision", which is also what the checkboxes then show.
    decisions: list[str] = []
    for raw in params.getlist("decisions"):
        decisions.extend(d for d in raw.split(",") if d in DECISIONS)
    if not decisions:
        decisions = list(DECISIONS)
    source = params.get("source") or None
    if source is not None and source not in ctx.config.scraping.boards:
        source = None
    criterion = params.get("criterion") or None
    criterion_type = None
    if criterion is not None:
        spec = ctx.config.criteria.get(criterion)
        if spec is None or criterion not in ctx.store.criterion_columns():
            criterion = None
        else:
            criterion_type = spec.question.type
    op = params.get("op") if params.get("op") in OPERATORS else None
    raw_value = (params.get("value") or "").strip()
    value = option = None
    if criterion and criterion_type == "score":
        value = _float(raw_value, 0.0, 1.0)
        if value is None or op is None:
            op, value = None, None
    elif criterion and criterion_type == "choice":
        allowed = ctx.config.criteria[criterion].question.options
        option = raw_value if raw_value in allowed else None
        op = None
    exclude_missing = params.get("exclude_missing") in ("1", "true", "on")

    # Criteria are read from the config: a criterion added today is filterable immediately,
    # even before a run has produced answers for it.
    known_columns = list(ctx.config.criteria)
    selectable = [*known_columns, *OPTIONAL_COLUMNS]
    default_columns = [column for column in known_columns if ctx.config.criteria[column].in_table]
    chosen = [c for raw in params.getlist("cols") for c in raw.split(",") if c in selectable]
    if params.getlist("cols"):
        visible = set(chosen)
    else:
        visible = set(default_columns)

    sort = params.get("sort") or "score_total"
    if not (sort in SORTS or (sort.startswith("crit:") and sort[5:] in ctx.config.criteria)):
        sort = "score_total"
    direction = "asc" if params.get("dir") == "asc" else "desc"
    run = params.get("run") or "all"
    run_id = int(run) if run.isdigit() else None
    return {
        "decisions": decisions, "source": source,
        "text": (params.get("q") or "").strip()[:80] or None,
        "location": (params.get("location") or "").strip()[:80] or None,
        "criterion": criterion, "criterion_type": criterion_type, "op": op, "value": value,
        "option": option, "exclude_missing": exclude_missing, "run": run, "run_id": run_id,
        "sort": sort, "dir": direction,
        "columns": visible, "selectable_columns": selectable, "criterion_names": known_columns,
        "criterion_columns": [c for c in known_columns if c in visible],
        "limit": _int(params.get("limit"), 50, 10, 200), "offset": _int(params.get("offset"), 0, 0, 100000),
    }


def jobs_url(filters: dict, **overrides) -> str:
    merged = {**filters, **overrides}
    query = {
        "decisions": ",".join(merged["decisions"]),
        "source": merged["source"] or "",
        "q": merged["text"] or "",
        "criterion": merged["criterion"] or "",
        "op": merged["op"] or "",
        "value": (f"{merged['value']:g}" if merged.get("value") is not None
                  else (merged.get("option") or "")),
        "exclude_missing": "1" if merged["exclude_missing"] else "",
        "cols": ",".join(sorted(merged["columns"])),
        "run": merged["run"], "sort": merged["sort"], "dir": merged["dir"],
        "limit": str(merged["limit"]), "offset": str(merged["offset"]),
    }
    return "/jobs?" + urlencode({key: val for key, val in query.items() if val != ""})


def detail_url(filters: dict, job_id: int) -> str:
    """The detail page carries the current query string, so "back" returns to the same list."""
    _, _, query = jobs_url(filters).partition("?")
    return f"/jobs/{job_id}?{query}" if query else f"/jobs/{job_id}"


def create_app(ctx: AppContext | None = None) -> FastAPI:
    if ctx is None:  # uvicorn --factory calls create_app() with no arguments
        from jobcaliber.bootstrap import build_context

        ctx = build_context(DEFAULT_ROOT)
    app = FastAPI(title="jobcaliber", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    app.state.build = f"{int((HERE / 'routes.py').stat().st_mtime)}"

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        """The list changes with every run: never let the browser serve a stale page."""
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
    # Autoescaping is explicit: the files are `.html.j2`, so the extension-based selector would
    # not escape them, and every title/description comes from a scraped board.
    env = Environment(
        loader=FileSystemLoader(str(HERE / "templates")),
        autoescape=select_autoescape(enabled_extensions=("html", "j2", "htm", "xml")),
    )
    templates = Jinja2Templates(env=env)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def render(request: Request, name: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, name, {"ctx": ctx, "build": app.state.build, **context})

    @app.get("/", response_class=HTMLResponse)
    def root() -> RedirectResponse:
        return RedirectResponse(jobs_url(default_filters()), status_code=303)

    @app.get("/jobs", response_class=HTMLResponse)
    def list_jobs(request: Request) -> HTMLResponse:
        filters = parse_filters(request, ctx)
        table = job_table(
            ctx.store, decisions=filters["decisions"], source=filters["source"],
            text=filters["text"], location=filters["location"],
            criterion=filters["criterion"], op=filters["op"],
            value=filters["value"], option=filters["option"],
            exclude_missing=filters["exclude_missing"], run_id=filters["run_id"],
            columns=filters["criterion_columns"], sort=filters["sort"], direction=filters["dir"],
            limit=filters["limit"], offset=filters["offset"],
        )
        criterion_options = []
        if filters["criterion"] and filters["criterion_type"] == "choice":
            criterion_options = list(ctx.config.criteria[filters["criterion"]].question.options)
        return render(request, "jobs.html.j2", table=table, filters=filters, jobs_url=jobs_url,
                      jobs_href=jobs_url(filters), detail_url=detail_url,
                      operators=OPERATORS, decisions=DECISIONS, criterion_options=criterion_options,
                      runs=ctx.store.runs(15), sources=ctx.config.scraping.boards,
                      columns=table.columns, visible=filters["columns"])

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def show_job(request: Request, job_id: int) -> HTMLResponse:
        detail = job_detail(ctx.store, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        filters = parse_filters(request, ctx)
        return render(request, "job.html.j2", detail=detail, filters=filters,
                      jobs_url=jobs_url, jobs_href=jobs_url(filters))

    @app.post("/jobs/{job_id}/feedback")
    def submit_feedback(job_id: int, verdict: str = Form(...)) -> RedirectResponse:
        if verdict not in ("good", "bad"):
            raise HTTPException(status_code=400, detail="verdict must be good or bad")
        evaluation = ctx.store.latest_evaluation(job_id)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="job has no evaluation yet")
        ctx.store.save_feedback(evaluation["id"], verdict)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/run")
    def request_run() -> RedirectResponse:
        ctx.store.request_run("manual")
        return RedirectResponse("/runs", status_code=303)

    @app.get("/runs", response_class=HTMLResponse)
    def list_runs(request: Request) -> HTMLResponse:
        return render(request, "runs.html.j2", runs=ctx.store.runs(30),
                      pending=ctx.store.pending_requests(), last=ctx.store.last_run())

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "db": str(ctx.store.path)})

    return app
