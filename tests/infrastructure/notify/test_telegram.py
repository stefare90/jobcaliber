"""The digest is built and delivered without touching the network in tests."""
import json

import httpx
import pytest

from jobcaliber.core.config import TelegramConfig
from jobcaliber.infrastructure.database.store import JobRow
from jobcaliber.infrastructure.notify import TelegramNotifier


def row(index: int, title: str = "Embedded Engineer", score: float = 80.0) -> JobRow:
    return JobRow(id=index, evaluation_id=index, external_id=f"https://it.linkedin.com/jobs/{index}",
                  title=title, company="Acme", source="linkedin", decision="pass",
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
    assert "Backend Dev" in text and "82.4" in text
    assert "https://it.linkedin.com/jobs/1" in text
    assert "http://192.168.1.28:8765/jobs?decisions=pass&amp;run=7" in text


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
