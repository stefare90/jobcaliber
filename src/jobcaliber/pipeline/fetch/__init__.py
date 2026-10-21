"""Fetch step: query the boards and normalise the rows into postings."""
from __future__ import annotations

from jobcaliber.pipeline.fetch.fetcher import Fetcher
from jobcaliber.pipeline.fetch.parsing import (
    clean_value,
    is_captcha_text,
    row_usable,
    to_job_posting,
)
from jobcaliber.pipeline.fetch.queries import build_queries

__all__ = [
    "Fetcher",
    "build_queries",
    "clean_value",
    "is_captcha_text",
    "row_usable",
    "to_job_posting",
]
