"""Evaluator: apply hard gates, then the weighted sum over weighted criteria."""
from __future__ import annotations

from jobcaliber.config import AppConfig, Criterion, GateAccept, GateMinScore
from jobcaliber.models import EvaluationResult, GateDecision, ScoringResult

NEUTRAL_SCORE = 0.5


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
        reasons: list[str] = []

        for key, criterion in self.config.criteria.items():
            if gate_fails(key, criterion, result):
                return EvaluationResult(
                    decision=GateDecision.DROP,
                    score_total=0.0,
                    confidence=round(result.confidence, 2),
                    reasons=[f"Gate '{key}' dropped: answer {result.answers.get(key)!r}"],
                    dropped_by=key,
                )

        weighted = {key: c for key, c in self.config.criteria.items() if c.weight > 0}
        total_weight = sum(c.weight for c in weighted.values())
        if total_weight <= 0:
            raise ValueError("no weighted criterion configured; nothing to score")

        sub_scores: dict[str, float] = {}
        weighted_sum = 0.0
        confidence = result.confidence
        for key, criterion in weighted.items():
            answer = result.answers.get(key, NEUTRAL_SCORE)
            score = float(answer) if isinstance(answer, (int, float)) else NEUTRAL_SCORE
            sub_scores[key] = round(score, 2)
            weighted_sum += criterion.weight * score
            if key in result.missing:
                penalty = self.config.penalties.get(key, 1.0)
                confidence *= penalty
                reasons.append(f"'{key}' not stated (confidence x{penalty})")

        normalized = (weighted_sum / total_weight) * 100.0
        telegram = self.config.notifications.telegram
        if normalized >= telegram.notify_threshold and confidence >= telegram.min_confidence:
            decision = GateDecision.PASS
        elif normalized >= telegram.review_threshold or confidence < telegram.min_confidence:
            decision = GateDecision.REVIEW
        else:
            decision = GateDecision.DROP
        if result.missing and decision == GateDecision.PASS:
            decision = GateDecision.REVIEW
            reasons.append("Missing data forces review")

        reasons.append(f"Score {normalized:.1f}, Confidence {confidence:.2f}")
        return EvaluationResult(
            decision=decision,
            score_total=round(normalized, 1),
            confidence=round(confidence, 2),
            sub_scores=sub_scores,
            reasons=reasons,
        )
