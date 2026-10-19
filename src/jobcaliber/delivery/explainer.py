"""Explainer: 2-line natural-language reason for a decided posting, via an LLM engine."""
from __future__ import annotations

from jobcaliber.ai.client import LLMClient
from jobcaliber.ai.prompts import PromptStore, render
from jobcaliber.models import EvaluationResult, JobPosting, SystemOneResult


class Explainer:
    def __init__(self, client: LLMClient, prompts: PromptStore):
        self.client = client
        self.system, self.template = prompts.load_llm("explainer")

    def explain(self, posting: JobPosting, s1: SystemOneResult, evaluation: EvaluationResult) -> str:
        values = {
            "title": posting.title,
            "company": posting.company,
            "location": posting.location_raw or "unknown",
            "score": evaluation.score_total,
            "confidence": evaluation.confidence,
            "core": s1.core_score,
            "tools": s1.tools_score,
            "contract": s1.contract_score,
            "pay": s1.pay_score,
            "location_bucket": s1.location_bucket.value,
            "reasons": "; ".join(evaluation.reasons),
        }
        return self.client.complete(
            user=render(self.template, values), system=render(self.system, values)
        ).strip()
