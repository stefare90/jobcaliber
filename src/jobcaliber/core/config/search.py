"""Search inputs: titles, locations and the exclusion list shown to the criteria."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Search(BaseModel):
    """What to look for. Location strings are board-ready (`Sardinia, Italy`, not `Sardegna`)."""

    titles: list[str] = Field(default_factory=list)
    on_site_locations: list[str] = Field(default_factory=list)
    remote_locations: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    job_type: str | None = "fulltime"

    def render_values(self) -> dict[str, str]:
        """Placeholders available to every criterion question (`{{search.*}}`)."""
        return {
            "search.titles": ", ".join(self.titles),
            "search.on_site_locations": ", ".join(self.on_site_locations),
            "search.remote_locations": ", ".join(self.remote_locations),
            "search.exclude": "; ".join(self.exclude) or "none",
        }


def validate_search(search: Search) -> None:
    if not [title for title in search.titles if title.strip()]:
        raise ValueError("search needs at least one non-empty title")
    if not ([loc for loc in search.on_site_locations if loc.strip()]
            or [loc for loc in search.remote_locations if loc.strip()]):
        raise ValueError("search needs at least one on_site_locations or remote_locations entry")
