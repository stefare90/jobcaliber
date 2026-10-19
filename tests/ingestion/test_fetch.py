import pandas as pd

from jobcaliber.config import ExtraSearch, LocationPrefs, Profile, Scraping, Skills
from jobcaliber.ingestion.fetch import (
    Fetcher,
    clean_value,
    is_captcha_text,
    normalize_fetch_location,
    row_usable,
    to_job_posting,
)
from jobcaliber.models import Query


def make_scraping(**over):
    defaults = dict(
        country="italy",
        hours_old=None,
        job_type="fulltime",
        boards=["linkedin", "indeed"],
        extra_searches=[ExtraSearch(keywords="Backend Developer", location="Italy")],
    )
    defaults.update(over)
    return Scraping(**defaults)


def make_profile(**over):
    defaults = dict(
        titles=["Software Engineer", "Embedded Software Engineer", "Python Developer"],
        location=LocationPrefs(primary="Sardegna", remote_ok=True, hybrid_max_km=40),
        skills=Skills(core={"c++": 5, "python": 4}, tools=["Qt", "CMake"]),
    )
    defaults.update(over)
    return Profile(**defaults)


def test_normalize_fetch_location():
    loc, is_rem = normalize_fetch_location("Sardegna")
    assert loc == "Sardinia, Italy"
    assert is_rem is False

    loc_rem, is_rem2 = normalize_fetch_location("Remote")
    assert loc_rem == "Italy"
    assert is_rem2 is True

    loc_to, is_rem3 = normalize_fetch_location("Torino")
    assert loc_to == "Torino"
    assert is_rem3 is False


def test_build_queries_auto_generates_primary_remote_and_extras():
    fetcher = Fetcher(make_scraping())
    queries = fetcher.build_queries(make_profile())
    assert [(q.keywords, q.location, q.remote) for q in queries] == [
        ("Software Engineer", "Sardinia, Italy", False),
        ("Software Engineer", "Italy", True),
        ("Embedded Software Engineer", "Sardinia, Italy", False),
        ("Embedded Software Engineer", "Italy", True),
        ("Python Developer", "Sardinia, Italy", False),
        ("Python Developer", "Italy", True),
        ("Backend Developer", "Italy", False),
    ]


def test_build_queries_skips_remote_when_disabled():
    fetcher = Fetcher(make_scraping(extra_searches=[]))
    profile = make_profile(location=LocationPrefs(primary="Sardegna", remote_ok=False))
    queries = fetcher.build_queries(profile)
    assert [q.location for q in queries] == ["Sardinia, Italy"] * 3


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
    posting = to_job_posting("linkedin", "q1", {"id": "7", "job_url": None, "company": "Acme",
                                                "title": "Dev", "location": "Cagliari",
                                                "date_posted": "2026-10-01", "min_amount": 38,
                                                "max_amount": 42, "description": "d"})
    assert posting.external_id == "linkedin:7"
    assert posting.search_id == "q1"
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
    records, stats = fetcher.fetch_board(Query("Dev", "Sardinia, Italy", "Sardegna", "Dev"), "linkedin", "q1")
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

    fetcher = Fetcher(make_scraping(page_size=50, page_cap=150), scrape_fn=fake, sleep_fn=lambda s: None)
    records, stats = fetcher.fetch_board(Query("Dev", "Italy", "Remote", "Dev", True), "linkedin", "q2")
    assert seen_offsets == [0, 50]
    assert stats.seen == 51
    assert len(records) == 51


def test_fetch_board_respects_page_cap():
    full = stub_frame([{"id": "a", "job_url": "http://a", "title": "Dev", "company": "Acme",
                        "location": "L", "description": "d", "date_posted": None,
                        "min_amount": None, "max_amount": None}] * 50)
    calls = []

    def fake(**kw):
        calls.append(kw["offset"])
        return full

    fetcher = Fetcher(make_scraping(page_size=50, page_cap=120), scrape_fn=fake, sleep_fn=lambda s: None)
    _, stats = fetcher.fetch_board(Query("Dev", "Italy", "R", "Dev", True), "linkedin", "q2")
    assert calls == [0, 50, 100]
    assert stats.seen == 150


def test_fetch_all_records_board_errors_without_raising():
    def boom(**kw):
        raise RuntimeError("board down")

    fetcher = Fetcher(make_scraping(), scrape_fn=boom, sleep_fn=lambda s: None)
    postings, per_board = fetcher.fetch_all(make_profile())
    assert postings == []
    assert per_board["linkedin"].errors and "board down" in per_board["linkedin"].errors[0]
