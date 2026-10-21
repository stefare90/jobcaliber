"""The fetch contract: what a query is and what the fetcher reports back."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Query:
    keywords: str
    location: str
    role: str
    remote: bool = False


@dataclass
class FetchStats:
    seen: int = 0
    usable: int = 0
    new: int = 0
    captcha_skipped: int = 0
    errors: list[str] = field(default_factory=list)
