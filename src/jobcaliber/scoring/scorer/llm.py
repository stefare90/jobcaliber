"""LLM scorer: one JSON answer per configured criterion, from an OpenAI-wire engine."""
from __future__ import annotations

from jobcaliber.ai.client import LLMClient
from jobcaliber.ai.prompts import PromptStore
from jobcaliber.config import Criterion, validate_criteria
from jobcaliber.models import JobPosting, ScoringResult
from jobcaliber.scoring.projection import build_llm_prompt
from jobcaliber.scoring.scorer.base import Scorer


@Scorer.register("llm")
class LLMScorer(Scorer):
    def __init__(self, client: LLMClient, criteria: dict[str, Criterion], prompts=None):
        validate_criteria(criteria)
        self.client = client
        self.criteria = criteria
        self.system, self.template = build_llm_prompt(criteria)

    def score_posting(self, posting: JobPosting) -> ScoringResult:
        values = {
            "title": posting.title,
            "company": posting.company,
            "location": posting.location_raw or "Not specified",
            "salary": f"{posting.salary_min or ''} - {posting.salary_max or ''}".strip(" -") or "Not stated",
            "description": posting.description or "(No description provided)",
        }
        raw = self.client.complete(user=self.render(self.template, values), system=self.system)
        parsed = self.parse_json_object(raw)
        missing = set(parsed.get("missing") or [])
        answers: dict[str, float | str] = {}
        for key, criterion in self.criteria.items():
            value = parsed.get(key)
            if key in missing or value is None:
                missing.add(key)
                answers[key] = 0.5 if criterion.question.type == "score" else criterion.question.missing
            elif criterion.question.type == "score":
                answers[key] = self.clamp(value)
            else:
                answers[key] = str(value)
        return self.build_result(
            answers=answers,
            missing=missing,
            confidence=parsed.get("confidence", 0.8),
            reason=str(parsed.get("summary_reason", "")),
        )

    @staticmethod
    def render(text: str, values: dict) -> str:
        from jobcaliber.ai.prompts import render
        return render(text, values)
