import pandas as pd

from jobcaliber.core.config import Scraping, Search
from jobcaliber.pipeline.fetch import (
    Fetcher,
    clean_value,
    is_captcha_text,
    row_usable,
    to_job_posting,
)
from jobcaliber.core.models import Query


def make_scraping(**over):
    defaults = dict(
        country="italy",
        hours_old=None,
        job_type="fulltime",
        boards=["linkedin", "indeed"],
        board_max_results={"linkedin": 300, "indeed": 500},
    )
    defaults.update(over)
    return Scraping(**defaults)


def make_search(**over):
    defaults = dict(
        titles=["Software Engineer", "Embedded Software Engineer", "Python Developer"],
        on_site_locations=["Sardinia, Italy"],
        remote_locations=["Italy"],
    )
    defaults.update(over)
    return Search(**defaults)


def test_build_queries_passes_location_strings_verbatim():
    fetcher = Fetcher(make_scraping())
    queries = fetcher.build_queries(make_search())
    assert [(q.keywords, q.location, q.remote) for q in queries] == [
        ("Software Engineer", "Sardinia, Italy", False),
        ("Embedded Software Engineer", "Sardinia, Italy", False),
        ("Python Developer", "Sardinia, Italy", False),
        ("Software Engineer", "Italy", True),
        ("Embedded Software Engineer", "Italy", True),
        ("Python Developer", "Italy", True),
    ]


def test_build_queries_without_remote_location():
    fetcher = Fetcher(make_scraping())
    search = make_search(remote_locations=[])
    queries = fetcher.build_queries(search)
    assert [q.location for q in queries] == ["Sardinia, Italy"] * 3
    assert all(q.remote is False for q in queries)


def test_clean_value_normalizes_nan():
    assert clean_value(None) is None
    assert clean_value(float("nan")) is None
    assert clean_value("nan") is None
    assert clean_value("  ") is None
    assert clean_value(" Inpeco ") == " Inpeco "


def test_row_usable_requires_title_company_url_and_no_captcha():
    good = {"title": "Dev", "company": "Acme", "job_url": "http://x", "description": "ok"}
    assert row_usable(good) is True
    assert row_usable({**good, "company": None}) is False
    assert row_usable({**good, "description": "solve this captcha now"}) is False
    assert is_captcha_text("unusual traffic detected") is True


def test_to_job_posting_maps_schema_fields():
    posting = to_job_posting("linkedin", Query("Dev", "Sardinia, Italy", "Dev"), {"id": "7", "job_url": None, "company": "Acme",
                                                "title": "Dev", "location": "Cagliari",
                                                "date_posted": "2026-10-01", "min_amount": 38,
                                                "max_amount": 42, "description": "d"})
    assert posting.external_id == "linkedin:7"
    assert posting.query_term == "Dev"
    assert posting.query_location == "Sardinia, Italy"
    assert posting.query_remote is False
    assert posting.salary_min == 38.0


def stub_frame(rows):
    return pd.DataFrame(rows)


def test_fetch_board_drops_captcha_and_dedups():
    pages = [stub_frame([
        {"id": "1", "job_url": "http://a", "title": "Dev", "company": "Acme",
         "location": "Cagliari", "description": "ok", "date_posted": None,
         "min_amount": None, "max_amount": None},
        {"id": "2", "job_url": "http://a", "title": "Dev", "company": "Acme",
         "location": "Cagliari", "description": "ok", "date_posted": None,
         "min_amount": None, "max_amount": None},
        {"id": "3", "job_url": "http://b", "title": "x", "company": "y",
         "location": "z", "description": "captcha challenge", "date_posted": None,
         "min_amount": None, "max_amount": None},
    ])]
    fetcher = Fetcher(make_scraping(), scrape_fn=lambda **kw: pages.pop(0), sleep_fn=lambda s: None)
    records, stats = fetcher.fetch_board(Query("Dev", "Sardinia, Italy", "Dev"), "linkedin")
    assert stats.seen == 3
    assert stats.usable == 2
    assert stats.new == 1
    assert [r.url for r in records] == ["http://a", "http://a"]


def test_fetch_board_paginates_until_short_page():
    full = stub_frame([{"id": str(i), "job_url": f"http://x/{i}", "title": "Dev",
                        "company": "Acme", "location": "L", "description": "d",
                        "date_posted": None, "min_amount": None, "max_amount": None}
                       for i in range(50)])
    short = stub_frame([{"id": "last", "job_url": "http://last", "title": "Dev",
                         "company": "Acme", "location": "L", "description": "d",
                         "date_posted": None, "min_amount": None, "max_amount": None}])
    seen_offsets = []

    def fake(**kw):
        seen_offsets.append(kw["offset"])
        return full if kw["offset"] == 0 else short

    fetcher = Fetcher(make_scraping(page_size=50), scrape_fn=fake, sleep_fn=lambda s: None)
    records, stats = fetcher.fetch_board(Query("Dev", "Italy", "Dev", True), "linkedin")
    assert seen_offsets == [0, 50]
    assert stats.seen == 51
    assert len(records) == 51


def test_fetch_board_respects_per_board_max_results():
    def page(start: int):
        return stub_frame([{"id": str(i), "job_url": f"http://x/{i}", "title": "Dev",
                            "company": "Acme", "location": "L", "description": "d",
                            "date_posted": None, "min_amount": None, "max_amount": None}
                           for i in range(start, start + 50)])

    calls = []

    def fake(**kw):
        calls.append(kw["offset"])
        return page(kw["offset"])

    scraping = make_scraping(page_size=50, board_max_results={"linkedin": 120, "indeed": 500})
    fetcher = Fetcher(scraping, scrape_fn=fake, sleep_fn=lambda s: None)
    _, stats = fetcher.fetch_board(Query("Dev", "Italy", "Dev", True), "linkedin")
    assert calls == [0, 50, 100]
    assert stats.seen == 150


def test_fetch_board_stops_when_a_page_adds_no_new_posting():
    repeated = stub_frame([{"id": "a", "job_url": "http://a", "title": "Dev", "company": "Acme",
                            "location": "L", "description": "d", "date_posted": None,
                            "min_amount": None, "max_amount": None}] * 50)
    calls = []

    def fake(**kw):
        calls.append(kw["offset"])
        return repeated

    fetcher = Fetcher(make_scraping(page_size=50), scrape_fn=fake, sleep_fn=lambda s: None)
    _, stats = fetcher.fetch_board(Query("Dev", "Italy", "Dev", True), "linkedin")
    assert calls == [0, 50]
    assert stats.new == 1


def test_fetch_all_records_board_errors_without_raising():
    def boom(**kw):
        raise RuntimeError("board down")

    fetcher = Fetcher(make_scraping(), scrape_fn=boom, sleep_fn=lambda s: None)
    postings, per_board = fetcher.fetch_all(make_search())
    assert postings == []
    assert per_board["linkedin"].errors and "board down" in per_board["linkedin"].errors[0]


def test_fetch_board_counts_skipped_captcha_rows():
    frame = stub_frame([
        {"id": "1", "job_url": "http://a", "title": "Dev", "company": "Acme",
         "location": "L", "description": "ok", "date_posted": None,
         "min_amount": None, "max_amount": None},
        {"id": "2", "job_url": "http://b", "title": "Dev", "company": "Acme",
         "location": "L", "description": "please solve this captcha", "date_posted": None,
         "min_amount": None, "max_amount": None},
    ])
    fetcher = Fetcher(make_scraping(), scrape_fn=lambda **kw: frame, sleep_fn=lambda s: None)
    records, stats = fetcher.fetch_board(Query("Dev", "Italy", "Dev"), "linkedin")
    assert stats.captcha_skipped == 1
    assert [r.url for r in records] == ["http://a"]
