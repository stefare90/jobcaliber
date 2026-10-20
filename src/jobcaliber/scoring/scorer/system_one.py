"""System One scorer: typed answers from a `/v1/systemone` engine (rizzo-flow, Jev)."""
from __future__ import annotations

from jobcaliber.ai.client import SystemOneClient
from jobcaliber.ai.prompts import PromptError
from jobcaliber.config import Criterion, validate_criteria
from jobcaliber.models import JobPosting, ScoringResult
from jobcaliber.scoring.projection import build_systemone_questions
from jobcaliber.scoring.scorer.base import Scorer


def validate_answers(questions: dict, criteria: dict[str, Criterion]) -> None:
    """Fail fast when the projected questions do not match the configured criteria."""
    if set(questions) != set(criteria):
        raise PromptError(
            f"projected questions {sorted(questions)} do not match criteria {sorted(criteria)}"
        )
    for key, question in questions.items():
        expected = criteria[key].question
        if question.get("type") != expected.type:
            raise PromptError(
                f"question '{key}': expected type '{expected.type}', projected '{question.get('type')}'"
            )


@Scorer.register("decision")
class SystemOneScorer(Scorer):
    def __init__(self, client: SystemOneClient, criteria: dict[str, Criterion], prompts=None):
        validate_criteria(criteria)
        self.client = client
        self.criteria = criteria
        self.questions = build_systemone_questions(criteria)
        validate_answers(self.questions, criteria)

    def score_posting(self, posting: JobPosting) -> ScoringResult:
        return self._parse(self.client.system_one(self.build_state(posting), self.questions))

    def _parse(self, data: dict) -> ScoringResult:
        answers: dict[str, float | str] = {}
        missing: set[str] = set()
        for key, criterion in self.criteria.items():
            question = criterion.question
            raw = data.get("answers", {}).get(key, {})
            if question.type == "score":
                levels = max(len(question.levels) - 1, 1)
                level = int(raw.get("score", 0))
                if question.missing is not None and level == question.missing:
                    answers[key], _ = 0.5, missing.add(key)
                else:
                    answers[key] = self.clamp(level / levels)
            else:
                choice = str(raw.get("choice", question.missing or ""))
                if question.missing is not None and choice == question.missing:
                    missing.add(key)
                answers[key] = choice
        confidences = [
            float(a["confidence"])
            for a in data.get("answers", {}).values()
            if isinstance(a, dict) and "confidence" in a
        ]
        confidence = sum(confidences) / len(confidences) if confidences else 0.85
        return self.build_result(answers=answers, missing=missing, confidence=confidence)
