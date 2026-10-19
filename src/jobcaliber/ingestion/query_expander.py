"""Query expander: alternate search titles proposed by an LLM, for extra_searches."""
from __future__ import annotations

from jobcaliber.ai.client import LLMClient
from jobcaliber.ai.prompts import PromptStore, render
from jobcaliber.config import Profile


class QueryExpander:
    def __init__(self, client: LLMClient, prompts: PromptStore):
        self.client = client
        self.system, self.template = prompts.load_llm("query_expander")

    def expand(self, profile: Profile, max_titles: int = 5) -> list[str]:
        values = {"titles": "\n".join(profile.titles), "max": max_titles}
        raw = self.client.complete(
            user=render(self.template, values), system=render(self.system, values)
        )
        titles: list[str] = []
        seen: set[str] = set()
        for line in raw.splitlines():
            title = line.strip().lstrip("-*0123456789. ").strip()
            if title and title.lower() not in seen:
                seen.add(title.lower())
                titles.append(title)
        return titles[:max_titles]
