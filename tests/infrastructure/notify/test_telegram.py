"""The digest is built and delivered without touching the network in tests."""
import json

import httpx
import pytest

from jobcaliber.core.config import TelegramConfig
from jobcaliber.infrastructure.database.store import JobRow
from jobcaliber.infrastructure.notify import TelegramNotifier


def row(index: int, title: str = "Embedded Engineer", score: float = 80.0,
        decision: str = "pass") -> JobRow:
    return JobRow(id=index, evaluation_id=index, external_id=f"https://it.linkedin.com/jobs/{index}",
                  title=title, company="Acme", source="linkedin", decision=decision,
                  score_total=score)


def notifier(handler, enabled=True):
    return TelegramNotifier(
        TelegramConfig(enabled=enabled, chat_id="42"), "http://192.168.1.28:8765", "tok",
        http=httpx.Client(transport=httpx.MockTransport(handler)), progress=lambda *_: None,
    )


def test_one_message_with_every_offer_and_its_ad_link():
    text = notifier(lambda request: httpx.Response(200, json={"ok": True})).build_message(
        [row(1, "Backend Dev", 82.4), row(2, "Embedded Eng", 78.1)], 7)
    assert "2 new offers" in text and "run 7" in text
    assert "2 pass" in text                       # the header counts what was sent
    assert "Backend Dev" in text and "82.4" in text
    assert "https://it.linkedin.com/jobs/1" in text
    assert "http://192.168.1.28:8765/jobs?decisions=pass,review&amp;run=7" in text


def test_the_run_filter_is_dropped_when_rows_come_from_several_runs():
    """A backlog digest spans runs: a `run=` filter would hide the offers it lists."""
    first, second = row(1, "From run 5", 82.0), row(2, "From run 6", 61.0, decision="review")
    first.run_id, second.run_id = 5, 6
    text = notifier(lambda request: httpx.Response(200, json={"ok": True})).build_message(
        [first, second], 6)
    assert "run=" not in text
    assert "/jobs?decisions=pass,review" in text


def test_the_run_filter_names_the_run_the_offers_come_from():
    only = row(1, "From run 5", 82.0)
    only.run_id = 5
    text = notifier(lambda request: httpx.Response(200, json={"ok": True})).build_message([only], 7)
    assert "decisions=pass,review&amp;run=5" in text


def test_a_review_is_labelled_and_counted_apart():
    text = notifier(lambda request: httpx.Response(200, json={"ok": True})).build_message(
        [row(1, "Good one", 82.0), row(2, "Borderline", 61.0, decision="review")], 7)
    assert "1 pass · 1 review" in text
    assert "<b>PASS</b> · <b>Good one</b>" in text
    assert "<b>REVIEW</b> · <b>Borderline</b>" in text


def test_a_long_list_is_truncated_and_says_how_many_are_left():
    text = notifier(lambda request: httpx.Response(200, json={"ok": True})).build_message(
        [row(i) for i in range(1, 13)], 3, max_offers=10)
    assert text.count("https://it.linkedin.com/jobs/") == 10
    assert "…and 2 more" in text


def test_the_message_never_exceeds_the_telegram_limit():
    text = notifier(lambda request: httpx.Response(200, json={"ok": True})).build_message(
        [row(i, "X" * 500) for i in range(1, 30)], 1)
    assert len(text) <= 4096


def test_titles_are_html_escaped():
    text = notifier(lambda request: httpx.Response(200, json={"ok": True})).build_message(
        [row(1, "<script>alert(1)</script>")], 1)
    assert "<script>" not in text and "&lt;script&gt;" in text


def test_send_posts_the_expected_payload():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    assert notifier(handler).send([row(1)], 5) is None
    assert seen["url"] == "https://api.telegram.org/bottok/sendMessage"
    assert seen["body"]["chat_id"] == "42"
    assert seen["body"]["parse_mode"] == "HTML"
    assert seen["body"]["disable_web_page_preview"] is True


def test_an_http_error_is_returned_not_raised():
    def handler(request):
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    error = notifier(handler).send([row(1)], 5)
    assert error is not None and "400" in error


def test_disabled_or_empty_sends_nothing():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    assert "disabled" in notifier(handler, enabled=False).send([row(1)], 1)
    assert "nothing" in notifier(handler).send([], 1)
    assert calls == []
