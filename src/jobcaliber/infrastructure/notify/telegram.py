"""Telegram delivery over plain HTTP: one digest message per run, no frameworks."""
from __future__ import annotations

import html

import httpx

from jobcaliber.core.config import TelegramConfig
from jobcaliber.infrastructure.database.store import JobRow

MAX_MESSAGE_CHARS = 4096  # Telegram rejects anything longer


class TelegramNotifier:
    def __init__(self, config: TelegramConfig, base_url: str, token: str,
                 http: httpx.Client | None = None, progress=print):
        self.config = config
        self.base_url = base_url
        self.token = token
        self.http = http or httpx.Client(timeout=15.0)
        self.progress = progress

    def build_message(self, rows: list[JobRow], run_id: int | None,
                      max_offers: int | None = None) -> str:
        """One HTML message: every pass offer with its ad link, plus a link to the filtered list."""
        limit = self.config.max_offers if max_offers is None else max_offers
        shown = rows[:limit]
        passed = sum(1 for row in rows if row.decision == "pass")
        reviewed = len(rows) - passed
        counts = " · ".join(part for part in (f"{passed} pass" if passed else "",
                                              f"{reviewed} review" if reviewed else "") if part)
        lines = [f"<b>{len(rows)} new offer{'s' if len(rows) != 1 else ''}</b>"
                 + (f" ({counts})" if counts else "")
                 + (f" · run {run_id}" if run_id is not None else ""), ""]
        for index, row in enumerate(shown, start=1):
            score = f" · {row.score_total:.1f}" if row.score_total is not None else ""
            decision = f"<b>{(row.decision or '').upper()}</b> · " if row.decision else ""
            lines.append(f"{index}. {decision}<b>{html.escape(row.title or '')}</b>"
                         f" — {html.escape(row.company or '')}{score}")
            if str(row.external_id).startswith("http"):
                lines.append(str(row.external_id))
            lines.append("")
        if len(rows) > len(shown):
            lines.append(f"…and {len(rows) - len(shown)} more")
        runs = {row.run_id for row in rows if row.run_id is not None}
        link = f"{self.base_url.rstrip('/')}/jobs?decisions=pass,review"
        if len(runs) == 1:
            link += f"&run={next(iter(runs))}"
        elif not runs and run_id is not None:
            link += f"&run={run_id}"
        lines.append(f'<a href="{html.escape(link, quote=True)}">All offers of this run</a>')
        text = "\n".join(lines)
        while len(text) > MAX_MESSAGE_CHARS and len(shown) > 1:
            text = self.build_message(shown[:-1], run_id, max_offers=len(shown) - 1)
        return text

    def send(self, rows: list[JobRow], run_id: int | None) -> str | None:
        """Deliver one digest; returns the error text when it failed, None when it went out."""
        if not self.config.enabled or not self.config.chat_id:
            return "telegram is disabled or has no chat_id"
        if not rows:
            return "nothing to notify"
        payload = {
            "chat_id": self.config.chat_id,
            "text": self.build_message(rows, run_id),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = self.http.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage", json=payload
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            return f"{type(error).__name__}: {error}"
        body = response.json() if response.content else {}
        if not body.get("ok", True):
            return f"telegram error: {body.get('description')}"
        return None
