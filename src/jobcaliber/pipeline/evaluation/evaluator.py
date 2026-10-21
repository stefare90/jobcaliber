"""Evaluator: gates, per-criterion thresholds, and a mean score used only for ordering."""
from __future__ import annotations

from jobcaliber.core.config import AppConfig, Criterion, GateAccept, GateMinScore
from jobcaliber.core.models import EvaluationResult, GateDecision, ScoringResult

NEUTRAL_SCORE = 0.5


def answer_value(result: ScoringResult, key: str) -> float | str | None:
    return result.answers.get(key)


def gate_fails(key: str, criterion: Criterion, result: ScoringResult) -> bool:
    """A gate drops only on an explicit negative answer; a missing answer never drops."""
    if key in result.missing:
        return False
    answer = result.answers.get(key)
    gate = criterion.gate
    if gate is True:
        return answer != "yes"
    if isinstance(gate, GateAccept):
        return answer not in gate.accept
    if isinstance(gate, GateMinScore):
        return not isinstance(answer, float) or answer < gate.min_score
    return False


class Evaluator:
    def __init__(self, config: AppConfig):
        self.config = config

    def evaluate(self, result: ScoringResult) -> EvaluationResult:
        criteria = self.config.criteria
        scored = {k: c for k, c in criteria.items() if c.gate is None or c.gate is False}
        confidence = result.confidence
        for key in sorted(result.missing & set(scored)):
            penalty = self.config.penalties.get(key, 1.0)
            confidence *= penalty

        for key, criterion in criteria.items():
            if gate_fails(key, criterion, result):
                return EvaluationResult(
                    decision=GateDecision.DROP, score_total=0.0, confidence=round(confidence, 2),
                    reasons=[f"Gate '{key}' dropped: answer {answer_value(result, key)!r}"],
                    dropped_by=key,
                )

        for key, criterion in scored.items():
            if key in result.missing or criterion.min_threshold is None:
                continue
            value = answer_value(result, key)
            if not isinstance(value, float) or value < criterion.min_threshold:
                return EvaluationResult(
                    decision=GateDecision.DROP, score_total=0.0, confidence=round(confidence, 2),
                    reasons=[f"'{key}' below min_threshold: {value!r} < {criterion.min_threshold}"],
                    dropped_by=key,
                )

        sub_scores = {
            key: round(float(answer_value(result, key)), 2)
            if isinstance(answer_value(result, key), float) else NEUTRAL_SCORE
            for key in scored
        }
        score_total = (sum(sub_scores.values()) / len(sub_scores) * 100) if sub_scores else 0.0

        reviews = [key for key in criteria if key in result.missing]
        if reviews:
            return EvaluationResult(
                decision=GateDecision.REVIEW, score_total=round(score_total, 1),
                confidence=round(confidence, 2), sub_scores=sub_scores,
                reasons=[f"'{key}' not verifiable" for key in reviews],
            )

        below = [
            key for key, criterion in scored.items()
            if criterion.apply_threshold is not None
            and (not isinstance(answer_value(result, key), float)
                 or answer_value(result, key) < criterion.apply_threshold)
        ]
        reasons = [f"'{key}' below apply_threshold" for key in below]
        if confidence < self.config.notifications.telegram.min_confidence:
            below.append("confidence")
            reasons.append(f"Confidence {confidence:.2f} below minimum")
        decision = GateDecision.REVIEW if below else GateDecision.PASS
        if below and not reasons:
            reasons.append("Below apply threshold")
        reasons.append(f"Mean {score_total:.1f}, Confidence {confidence:.2f}")
        return EvaluationResult(
            decision=decision, score_total=round(score_total, 1), confidence=round(confidence, 2),
            sub_scores=sub_scores, reasons=reasons,
        )
