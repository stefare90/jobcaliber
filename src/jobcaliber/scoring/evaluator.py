"""Evaluator applying job_filters, hard gates, and weighted scoring onto SystemOneResult."""
from __future__ import annotations

from jobcaliber.config import AppConfig
from jobcaliber.models import (
    EvaluationResult,
    GateDecision,
    LocationBucket,
    SystemOneResult,
)


class Evaluator:
    def __init__(self, config: AppConfig):
        self.config = config

    def evaluate(self, s1: SystemOneResult) -> EvaluationResult:
        filters = self.config.job_filters
        reasons: list[str] = []

        if s1.location_bucket == LocationBucket.ELSEWHERE and filters.location.mode == "hard_gate":
            return EvaluationResult(
                decision=GateDecision.DROP,
                score_total=0.0,
                confidence=s1.confidence,
                reasons=[f"Location dropped: {s1.location_bucket.value}"],
            )

        if filters.pay.mode in ("hybrid", "hard_gate") and not s1.pay_missing and s1.pay_score == 0.0:
            return EvaluationResult(
                decision=GateDecision.DROP,
                score_total=0.0,
                confidence=s1.confidence,
                reasons=["Pay dropped: compensation below minimum expectations"],
            )

        s_loc = filters.location.bucket_scores[s1.location_bucket.value]
        weights = {
            "core": (filters.core_skills.weight, s1.core_score),
            "tools": (filters.tools.weight, s1.tools_score),
            "contract": (filters.contract.weight, s1.contract_score),
            "pay": (filters.pay.weight, s1.pay_score),
            "location": (filters.location.weight, s_loc),
        }
        total_weight = sum(w for w, _ in weights.values())
        weighted_sum = sum(w * s for w, s in weights.values())
        normalized_score = (weighted_sum / total_weight) * 100.0 if total_weight > 0 else 0.0

        penalties = filters.confidence_penalties
        confidence = s1.confidence
        if s1.location_bucket == LocationBucket.UNKNOWN:
            confidence *= penalties.location_unknown
            reasons.append("Unknown location (confidence penalty)")
        if s1.pay_missing:
            confidence *= penalties.pay_missing
            reasons.append("Missing pay (confidence penalty)")

        telegram = self.config.notifications.telegram
        if normalized_score >= telegram.notify_threshold and confidence >= telegram.min_confidence:
            decision = GateDecision.PASS
        elif normalized_score >= telegram.review_threshold or confidence < telegram.min_confidence:
            decision = GateDecision.REVIEW
        else:
            decision = GateDecision.DROP

        reasons.append(f"Score {normalized_score:.1f}, Confidence {confidence:.2f}")

        return EvaluationResult(
            decision=decision,
            score_total=round(normalized_score, 1),
            confidence=round(confidence, 2),
            sub_scores={name: round(score, 2) for name, (_, score) in weights.items()},
            reasons=reasons,
        )
