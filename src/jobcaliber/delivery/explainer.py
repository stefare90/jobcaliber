"""Explainer: 2-line natural-language reason for a decided posting, via an LLM engine."""
from __future__ import annotations

from jobcaliber.ai.client import LLMClient
from jobcaliber.ai.prompts import PromptStore, render
from jobcaliber.models import EvaluationResult, JobPosting, ScoringResult


class Explainer:
    def __init__(self, client: LLMClient, prompts: PromptStore):
        self.client = client
        self.system, self.template = prompts.load_llm("explainer")

    def explain(self, posting: JobPosting, result: ScoringResult, evaluation: EvaluationResult) -> str:
        values = {
            "title": posting.title,
            "company": posting.company,
            "location": posting.location_raw or "unknown",
            "score": evaluation.score_total,
            "confidence": evaluation.confidence,
            "sub_scores": ", ".join(f"{key} {value}" for key, value in evaluation.sub_scores.items()),
            "missing": ", ".join(sorted(result.missing)) or "none",
            "reasons": "; ".join(evaluation.reasons),
        }
        return self.client.complete(
            user=render(self.template, values), system=render(self.system, values)
        ).strip()
