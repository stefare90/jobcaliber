"""Read models: turn Store rows into exactly what a template needs, in three queries."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobcaliber.infrastructure.database import Store


@dataclass
class JobTable:
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


def job_table(store: Store, *, decisions=None, source=None, text=None, location=None,
              criterion=None, op=None, value=None, option=None, exclude_missing=False,
              run_id=None, columns=None, sort="score_total", direction="desc",
              limit=50, offset=0) -> JobTable:
    total = store.count_jobs(
        decisions=decisions, source=source, text=text, location=location, criterion=criterion,
        op=op, value=value, option=option, exclude_missing=exclude_missing, run_id=run_id,
    )
    # An offset past the last page would render an empty table: clamp to the last page.
    if total and offset >= total:
        offset = ((total - 1) // limit) * limit
    rows = store.jobs(
        decisions=decisions, source=source, text=text, location=location, criterion=criterion,
        op=op, value=value, option=option, exclude_missing=exclude_missing, run_id=run_id,
        sort=sort, direction=direction, limit=limit, offset=offset,
    )
    evaluation_ids = [row.evaluation_id for row in rows]
    answers = store.answers_for(evaluation_ids)
    missing_by_eval = store.missing_for(evaluation_ids)
    feedback = store.feedback_for(evaluation_ids)
    return JobTable(
        rows=[
            {
                "job": row,
                "answers": answers.get(row.evaluation_id, {}),
                "missing": missing_by_eval.get(row.evaluation_id, set()),
                "feedback": feedback.get(row.evaluation_id),
            }
            for row in rows
        ],
        columns=columns if columns is not None else store.criterion_columns(),
        total=total,
        offset=offset,
        limit=limit,
    )


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
    job = {**job, "description": normalize_description(job.get("description"))}
    evaluation = store.latest_evaluation(job_id)
    if evaluation is None:
        return {"job": job, "evaluation": None, "answers": {}, "missing": set(), "feedback": None}
    evaluation_id = evaluation["id"]
    return {
        "job": job,
        "evaluation": evaluation,
        "answers": store.answers_for([evaluation_id]).get(evaluation_id, {}),
        "missing": store.missing_for([evaluation_id]).get(evaluation_id, set()),
        "feedback": store.feedback_for([evaluation_id]).get(evaluation_id),
    }
