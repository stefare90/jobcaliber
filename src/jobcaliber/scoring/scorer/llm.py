"""LLM scorer: the 5 dimensions as JSON, from an OpenAI/Ollama chat engine."""
from __future__ import annotations

from jobcaliber.ai.client import LLMClient
from jobcaliber.ai.prompts import PromptStore, render
from jobcaliber.config import Profile
from jobcaliber.models import JobPosting, SystemOneResult
from jobcaliber.scoring.scorer.base import Scorer


@Scorer.register("llm")
class LLMScorer(Scorer):
    def __init__(self, client: LLMClient, profile: Profile, prompts: PromptStore):
        self.client = client
        self.values = self.question_values(profile)
        self.system, self.template = prompts.load_llm("scoring_llm")

    def score_posting(self, posting: JobPosting) -> SystemOneResult:
        values = {
            **self.values,
            "title": posting.title,
            "company": posting.company,
            "location": posting.location_raw or "Not specified",
            "salary": f"{posting.salary_min or ''} - {posting.salary_max or ''}".strip(" -") or "Not stated",
            "description": posting.description or "(No description provided)",
        }
        raw = self.client.complete(user=render(self.template, values), system=render(self.system, values))
        parsed = self.parse_json_object(raw)
        return self.build_result(
            core=parsed.get("core_score", 0.5), tools=parsed.get("tools_score", 0.5),
            contract=parsed.get("contract_score", 0.5), pay=parsed.get("pay_score", 0.5),
            pay_missing=parsed.get("pay_missing", True),
            location=parsed.get("location_bucket", "unknown"),
            confidence=parsed.get("confidence", 0.8),
            reason=str(parsed.get("summary_reason", "")),
        )
