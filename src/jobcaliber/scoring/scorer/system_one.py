"""System One scorer: typed answers from a `/v1/systemone` engine (rizzo-flow, Jev)."""
from __future__ import annotations

from jobcaliber.ai.client import SystemOneClient
from jobcaliber.ai.prompts import PromptError, PromptStore
from jobcaliber.config import Profile
from jobcaliber.models import JobPosting, LocationBucket, SystemOneResult
from jobcaliber.scoring.scorer.base import Scorer

REQUIRED_SCORE_QUESTIONS = ("core", "tools", "contract", "pay")


def validate_systemone_questions(questions: dict) -> None:
    """Fail fast when the prompt file does not match the domain model."""
    for name in REQUIRED_SCORE_QUESTIONS:
        q = questions.get(name)
        if not q or q.get("type") != "score" or len(q.get("criteria", [])) < 2:
            raise PromptError(f"scoring_systemone question '{name}' must be a score question with >=2 criteria")

    location = questions.get("location")
    if not location or location.get("type") != "choice":
        raise PromptError("scoring_systemone question 'location' must be a choice question")
    buckets = set(location.get("criteria", {}))
    expected = {b.value for b in LocationBucket}
    if buckets != expected:
        raise PromptError(f"location criteria {sorted(buckets)} must equal LocationBucket values {sorted(expected)}")

    if not any("not stated" in str(c).lower() for c in questions["pay"]["criteria"]):
        raise PromptError("pay criteria must include a 'not stated' level (used for pay_missing)")


@Scorer.register("decision")
class SystemOneScorer(Scorer):
    def __init__(self, client: SystemOneClient, profile: Profile, prompts: PromptStore):
        self.client = client
        self.questions = prompts.load_json("scoring_systemone", self.question_values(profile))
        validate_systemone_questions(self.questions)
        self.max_levels = {
            name: max(len(q.get("criteria", [])) - 1, 1)
            for name, q in self.questions.items()
            if q.get("type") == "score"
        }
        self.pay_missing_level = self.missing_level(self.questions.get("pay", {}))

    def score_posting(self, posting: JobPosting) -> SystemOneResult:
        data = self.client.system_one(self.build_state(posting), self.questions)
        return self._parse(data)

    def _parse(self, data: dict) -> SystemOneResult:
        answers = data.get("answers", {})
        scores: dict[str, float] = {}
        for name, levels in self.max_levels.items():
            raw = float(answers[name]["score"]) if "score" in answers.get(name, {}) else levels / 2
            scores[name] = self.clamp(raw / levels)

        pay_ans = answers.get("pay", {})
        pay_missing = round(float(pay_ans.get("score", self.pay_missing_level))) == self.pay_missing_level

        confidences = [float(a["confidence"]) for a in answers.values()
                       if isinstance(a, dict) and "confidence" in a]
        confidence = sum(confidences) / len(confidences) if confidences else 0.85

        return self.build_result(
            core=scores.get("core", 0.5), tools=scores.get("tools", 0.5),
            contract=scores.get("contract", 0.5), pay=scores.get("pay", 0.5),
            pay_missing=pay_missing, location=answers.get("location", {}).get("choice", "unknown"),
            confidence=confidence,
        )
