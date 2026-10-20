"""Query expander: alternate search titles proposed by an LLM, for the search block."""
from __future__ import annotations

from jobcaliber.ai.client import LLMClient
from jobcaliber.ai.prompts import PromptStore, render
from jobcaliber.config import Search


class QueryExpander:
    def __init__(self, client: LLMClient, prompts: PromptStore):
        self.client = client
        self.system, self.template = prompts.load_llm("query_expander")

    def expand(self, search: Search, max_titles: int = 5) -> list[str]:
        values = {"titles": "\n".join(search.titles), "max": max_titles}
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
