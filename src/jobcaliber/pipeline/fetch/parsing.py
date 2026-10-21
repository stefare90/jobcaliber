"""Row parsing: board rows in, `JobPosting` out. No network, no policy."""
from __future__ import annotations

import math

from jobcaliber.core.models import JobPosting, Query

POLITENESS_GAP_S = 2

CAPTCHA_MARKERS = [
    "captcha",
    "are you a robot",
    "unusual traffic",
    "verify you are human",
    "access denied - ip",
    "datadome",
]


def clean_value(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    if s.lower() in ("nan", "none", "nat", ""):
        return None
    return v


def is_captcha_text(text: str) -> bool:
    return any(m in text.lower() for m in CAPTCHA_MARKERS)


def row_usable(row: dict) -> bool:
    if not (clean_value(row.get("title")) and clean_value(row.get("company")) and clean_value(row.get("job_url"))):
        return False
    blob = " ".join(str(row.get(k, "") or "") for k in ("title", "description", "company"))
    return not is_captcha_text(blob)


def to_job_posting(board: str, query: Query, row: dict) -> JobPosting:
    s_min = clean_value(row.get("min_amount"))
    s_max = clean_value(row.get("max_amount"))
    return JobPosting(
        external_id=str(row.get("job_url") or f"{board}:{row.get('id')}"),
        url=str(row.get("job_url") or ""),
        company=str(row.get("company") or ""),
        title=str(row.get("title") or ""),
        source=board,
        location_raw=clean_value(row.get("location")),
        posted_at=str(row.get("date_posted")) if clean_value(row.get("date_posted")) else None,
        salary_min=float(s_min) if s_min is not None else None,
        salary_max=float(s_max) if s_max is not None else None,
        description=clean_value(row.get("description")),
        query_term=query.keywords,
        query_location=query.location,
        query_remote=query.remote,
    )
