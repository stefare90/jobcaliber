"""Search-driven job fetch via JobSpy. Scraping only: no gates, no scoring."""
from __future__ import annotations

import math
import time

from jobspy import scrape_jobs

from jobcaliber.core.config import Scraping, Search
from jobcaliber.core.models import FetchStats, JobPosting, Query
from jobcaliber.pipeline.fetch.parsing import (
    clean_value,
    is_captcha_text,
    row_usable,
    to_job_posting,
)
from jobcaliber.pipeline.fetch.queries import build_queries

POLITENESS_GAP_S = 2


class Fetcher:
    def __init__(self, scraping: Scraping, scrape_fn=None, sleep_fn=time.sleep, on_page=None):
        self.scraping = scraping
        self.scrape_fn = scrape_fn or self._scrape
        self.sleep_fn = sleep_fn
        self.on_page = on_page
        self.seen_ids: set[str] = set()

    @property
    def boards(self) -> list[str]:
        return self.scraping.boards

    @property
    def page_size(self) -> int:
        return self.scraping.page_size

    def build_queries(self, search: Search) -> list[Query]:
        return build_queries(search)

    def _scrape(self, **kwargs):
        return scrape_jobs(**kwargs)

    def fetch_board(self, query: Query, board: str) -> tuple[list[JobPosting], FetchStats]:
        stats = FetchStats()
        postings: list[JobPosting] = []
        max_results = self.scraping.max_results(board)
        offset = 0
        while True:
            df = self.scrape_fn(
                site_name=board,
                search_term=query.keywords,
                location=query.location,
                is_remote=query.remote,
                results_wanted=self.page_size,
                offset=offset,
                hours_old=self.scraping.hours_old,
                country_indeed=self.scraping.country,
                job_type=self.scraping.job_type,
                linkedin_fetch_description=(board == "linkedin"),
                verbose=0,
            )
            batch = len(df) if df is not None else 0
            stats.seen += batch
            new_ids = 0
            if df is not None and batch > 0:
                for _, r in df.iterrows():
                    row = {k: clean_value(v) for k, v in r.to_dict().items()}
                    blob = " ".join(str(row.get(k, "") or "") for k in ("title", "description", "company"))
                    if is_captcha_text(blob):
                        stats.captcha_skipped += 1
                        continue
                    if row_usable(row):
                        stats.usable += 1
                    posting = to_job_posting(board, query, row)
                    if posting.external_id not in self.seen_ids:
                        self.seen_ids.add(posting.external_id)
                        stats.new += 1
                        new_ids += 1
                    postings.append(posting)
            if batch < self.page_size or stats.seen >= max_results or new_ids == 0:
                break
            offset += self.page_size
            if self.on_page is not None:
                self.on_page(query, board, offset, stats.seen)
            self.sleep_fn(POLITENESS_GAP_S)
        return postings, stats

    def fetch_all(self, search: Search) -> tuple[list[JobPosting], dict[str, FetchStats]]:
        queries = self.build_queries(search)
        all_postings: list[JobPosting] = []
        per_board: dict[str, FetchStats] = {b: FetchStats() for b in self.boards}
        for qi, query in enumerate(queries, start=1):
            for board in self.boards:
                try:
                    postings, stats = self.fetch_board(query, board)
                except Exception as e:
                    stats = FetchStats(errors=[f"q{qi}: {type(e).__name__}: {e}"])
                    postings = []
                all_postings.extend(postings)
                agg = per_board[board]
                agg.seen += stats.seen
                agg.usable += stats.usable
                agg.new += stats.new
                agg.errors.extend(stats.errors)
                self.sleep_fn(POLITENESS_GAP_S)
        return all_postings, per_board
