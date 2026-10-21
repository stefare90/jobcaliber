"""The query matrix: every title crossed with every configured location."""
from __future__ import annotations

from jobcaliber.core.config import Search
from jobcaliber.core.models import Query


def build_queries(search: Search) -> list[Query]:
    """Board queries are board-ready strings: no geo or language transformation happens here."""
    titles = [title.strip() for title in search.titles if title.strip()]
    queries = [
        Query(keywords=title, location=loc.strip(), role=title, remote=False)
        for title in titles
        for loc in search.on_site_locations
        if loc.strip()
    ]
    queries += [
        Query(keywords=title, location=loc.strip(), role=title, remote=True)
        for title in titles
        for loc in search.remote_locations
        if loc.strip()
    ]
    return queries
