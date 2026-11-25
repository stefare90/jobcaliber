"""LLM scorer: one JSON answer per configured criterion, from an OpenAI-wire engine."""
from __future__ import annotations

from jobcaliber.infrastructure.ai.client import LLMClient
from jobcaliber.core.config import Criterion, validate_criteria
from jobcaliber.core.domain import JobPosting, ScoringResult
from jobcaliber.pipeline.scoring.projection import build_llm_prompt
from jobcaliber.pipeline.scoring.scorer.base import Scorer

REPAIR = (
    "Your previous answer was rejected for these reasons:\n{errors}\n"
    "Answer again with one JSON object only, using the keys and the level numbers shown above."
)


@Scorer.register("llm")
class LLMScorer(Scorer):
    def __init__(self, client: LLMClient, criteria: dict[str, Criterion], prompts=None,
                 values: dict[str, str] | None = None):
        validate_criteria(criteria)
        self.client = client
        self.criteria = criteria
        self.values = values or {}
        self.system, self.template = build_llm_prompt(criteria, self.values)

    def score_posting(self, posting: JobPosting) -> ScoringResult:
        values = {
            "title": posting.title,
            "company": posting.company,
            "location": posting.location_raw or "Not specified",
            "salary": f"{posting.salary_min or ''} - {posting.salary_max or ''}".strip(" -") or "Not stated",
            "description": posting.description or "(No description provided)",
        }
        user = self.render(self.template, values)
        parsed, errors = self._ask(user)
        if errors:
            # One corrective round: a chat model that mislabelled a level is worth a second call,
            # but never a third — the run must not stall on one posting.
            parsed, errors = self._ask(user + "\n\n" + REPAIR.format(errors="\n".join(f"- {e}" for e in errors)))
        return self._build(parsed, errors)

    def _ask(self, user: str) -> tuple[dict, list[str]]:
        try:
            parsed = self.parse_json_object(self.client.complete(user=user, system=self.system))
        except Exception as error:
            return {}, [f"the answer is not a JSON object ({type(error).__name__})"]
        return parsed, self._validate(parsed)

    def _validate(self, parsed: dict) -> list[str]:
        errors: list[str] = []
        missing = parsed.get("missing") or []
        if not isinstance(missing, list):
            errors.append('"missing" must be a list of keys')
        for key in set(parsed) - set(self.criteria) - {"missing", "confidence", "summary_reason"}:
            errors.append(f'unknown key "{key}"')
        for key, criterion in self.criteria.items():
            question = criterion.question
            value = parsed.get(key)
            if value is None:
                if key not in (missing if isinstance(missing, list) else []):
                    errors.append(f'"{key}" is missing from the answer and not listed in "missing"')
                continue
            if question.type == "score":
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    errors.append(f'"{key}" must be a level number, got {value!r}')
                    continue
                top = max(len(question.levels) - 1, 1)
                if not (0 <= number <= top):
                    errors.append(f'"{key}" level {number} is outside 0-{top}')
            elif str(value).strip().lower() not in {o.lower() for o in question.options}:
                errors.append(f'"{key}" must be one of {list(question.options)}, got {value!r}')
        return errors

    def _build(self, parsed: dict, errors: list[str]) -> ScoringResult:
        """Turn the answers into a result; keys that stay invalid become `missing` (never a drop)."""
        missing = {str(key) for key in (parsed.get("missing") or []) if key in self.criteria}
        for error in errors:
            for key in self.criteria:
                if f'"{key}"' in error:
                    missing.add(key)
        answers: dict[str, float | str] = {}
        for key, criterion in self.criteria.items():
            question = criterion.question
            value = parsed.get(key)
            if key in missing or value is None:
                if question.missing is None:
                    answers[key] = 0.0 if question.type == "score" else ""
                else:
                    missing.add(key)
                    answers[key] = 0.5 if question.type == "score" else question.missing
            elif question.type == "score":
                answers[key] = self._level(question, value)
            else:
                answers[key] = str(value).strip()
        return self.build_result(
            answers=answers,
            missing=missing,
            confidence=parsed.get("confidence", 0.8),
            reason=str(parsed.get("summary_reason", "")),
        )

    def _level(self, question, value) -> float:
        """A level number becomes the same fraction a decision engine reports (2 of 4 → 0.67)."""
        number = float(value)
        top = max(len(question.levels) - 1, 1)
        if number.is_integer() and 0 <= number <= top:
            return self.clamp(number / top)
        return self.clamp(number)

    @staticmethod
    def render(text: str, values: dict) -> str:
        from jobcaliber.infrastructure.ai.prompts import render
        return render(text, values)
