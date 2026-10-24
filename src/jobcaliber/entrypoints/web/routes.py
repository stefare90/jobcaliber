"""HTTP surface: parse the query string, ask the read models, render. No business logic."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from jobcaliber.bootstrap import AppContext

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parents[3]
from jobcaliber.core.formatting import DEFAULT_FORMAT, local_time
from jobcaliber.entrypoints.web.filters import (
    DECISIONS,
    OP_LABELS,
    default_filters,
    detail_url,
    jobs_url,
    parse_filters,
)
from jobcaliber.entrypoints.web.readmodels import job_detail, job_table
from jobcaliber.infrastructure.database import APPLICATION_STATES


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
    env.filters["localtime"] = lambda value, fmt=DEFAULT_FORMAT: local_time(value, ctx.tz, fmt)
    templates = Jinja2Templates(env=env)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def render(request: Request, name: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, name, {"ctx": ctx, "build": app.state.build, **context})

    @app.get("/", response_class=HTMLResponse)
    def root() -> RedirectResponse:
        return RedirectResponse(jobs_url(default_filters()), status_code=303)

    @app.get("/jobs", response_class=HTMLResponse)
    def list_jobs(request: Request) -> HTMLResponse:
        filters = parse_filters(request.query_params, ctx)
        table = job_table(
            ctx.store, decisions=filters["decisions"],
            filters=filters["filters"], exclude_missing=filters["exclude_missing"],
            columns=filters["criterion_columns"], sort=filters["sort"], direction=filters["dir"],
            limit=filters["limit"], offset=filters["offset"],
        )
        return render(request, "jobs.html.j2", table=table, filters=filters, jobs_url=jobs_url,
                      jobs_href=jobs_url(filters), detail_url=detail_url,
                      operators=OP_LABELS, decisions=DECISIONS,
                      runs=ctx.store.runs(15), sources=ctx.config.scraping.boards,
                      columns=table.columns, visible=filters["columns"])

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def show_job(request: Request, job_id: int) -> HTMLResponse:
        detail = job_detail(ctx.store, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        filters = parse_filters(request.query_params, ctx)
        return render(request, "job.html.j2", detail=detail, filters=filters,
                      jobs_url=jobs_url, jobs_href=jobs_url(filters))

    @app.post("/jobs/{job_id}/application")
    def submit_application(job_id: int, state: str = Form(...),
                           back: str = Form("")) -> RedirectResponse:
        if state not in (*APPLICATION_STATES, "none"):
            raise HTTPException(status_code=400, detail=f"unknown state {state!r}")
        if ctx.store.job(job_id) is None:
            raise HTTPException(status_code=404, detail="unknown job")
        if state == "none":
            ctx.store.clear_application(job_id)
        else:
            ctx.store.save_application(job_id, state)
        return RedirectResponse(back or "/jobs", status_code=303)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/run")
    def request_run() -> RedirectResponse:
        ctx.store.request_run("manual")
        return RedirectResponse("/runs", status_code=303)

    @app.get("/applications", response_class=HTMLResponse)
    def list_applications(request: Request, state: str = "all") -> HTMLResponse:
        wanted = None if state in ("all", "") else state
        rows = ctx.store.applications(wanted)
        jobs = {job_id: ctx.store.job(job_id) for job_id in [row.job_id for row in rows]}
        return render(request, "applications.html.j2",
                      rows=[{"application": row, "job": jobs.get(row.job_id)} for row in rows],
                      state=state, total=len(rows))

    @app.get("/applications.csv", response_class=PlainTextResponse)
    def export_applications(state: str = "all") -> PlainTextResponse:
        wanted = None if state in ("all", "") else state
        rows = ctx.store.applications(wanted)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["state", "updated_at", "title", "company", "board", "score", "url"])
        for row in rows:
            job = ctx.store.job(row.job_id) or {}
            evaluation = ctx.store.latest_evaluation(row.job_id) or {}
            writer.writerow([
                row.state, row.updated_at, job.get("title", ""), job.get("company", ""),
                job.get("source", ""), evaluation.get("score_total", ""),
                job.get("external_id", ""),
            ])
        return PlainTextResponse(
            buffer.getvalue(),
            headers={"Content-Disposition": 'attachment; filename="applications.csv"'},
        )

    @app.get("/runs", response_class=HTMLResponse)
    def list_runs(request: Request) -> HTMLResponse:
        return render(request, "runs.html.j2", runs=ctx.store.runs(30),
                      pending=ctx.store.pending_requests(), last=ctx.store.last_run())

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "db": str(ctx.store.path)})

    return app