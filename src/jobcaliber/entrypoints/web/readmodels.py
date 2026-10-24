"""Read models: turn Store rows into exactly what a template needs, in three queries."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

from jobcaliber.infrastructure.database import Store


@dataclass
class JobTable:
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


def job_table(store: Store, *, decisions=None, text=None, filters=(), exclude_missing=False,
              columns=None, sort="score_total", direction="desc",
              limit=50, offset=0) -> JobTable:
    total = store.count_jobs(
        decisions=decisions, text=text, filters=filters, exclude_missing=exclude_missing,
    )
    # An offset past the last page would render an empty table: clamp to the last page.
    if total and offset >= total:
        offset = ((total - 1) // limit) * limit
    rows = store.jobs(
        decisions=decisions, text=text, filters=filters, exclude_missing=exclude_missing,
        sort=sort, direction=direction, limit=limit, offset=offset,
    )
    evaluation_ids = [row.evaluation_id for row in rows]
    answers = store.answers_for(evaluation_ids)
    missing_by_eval = store.missing_for(evaluation_ids)
    applications = store.applications_for([row.id for row in rows])
    return JobTable(
        rows=[
            {
                "job": row,
                "answers": answers.get(row.evaluation_id, {}),
                "missing": missing_by_eval.get(row.evaluation_id, set()),
                "application": applications.get(row.id),
            }
            for row in rows
        ],
        columns=columns if columns is not None else store.criterion_columns(),
        total=total,
        offset=offset,
        limit=limit,
    )


# `html=False` escapes any raw tag in the posting: boards are untrusted input, and rendering
# markdown must not become a way to inject markup.
_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})


def render_markdown(text: str | None) -> str:
    if not text:
        return ""
    return _MARKDOWN.render(text)


def normalize_description(text: str | None) -> str:
    """Board descriptions carry runs of blank, indented lines: keep one empty line between blocks."""
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+(?=\n)", "", normalized)      # blank lines are often indented
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def job_detail(store: Store, job_id: int) -> dict | None:
    job = store.job(job_id)
    if job is None:
        return None
    description = normalize_description(job.get("description"))
    job = {**job, "description": description, "description_html": render_markdown(description)}
    evaluation = store.latest_evaluation(job_id)
    if evaluation is None:
        return {"job": job, "evaluation": None, "answers": {}, "missing": set(),
                "application": store.application(job_id)}
    evaluation_id = evaluation["id"]
    return {
        "job": job,
        "evaluation": evaluation,
        "answers": store.answers_for([evaluation_id]).get(evaluation_id, {}),
        "missing": store.missing_for([evaluation_id]).get(evaluation_id, set()),
        "application": store.application(job_id),
    }
