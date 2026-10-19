"""Scoring: Scorer interface + registry, concrete scorers, and the Evaluator."""
from __future__ import annotations

from jobcaliber.scoring.scorer.base import Scorer
from jobcaliber.scoring.evaluator import Evaluator
# Import the concrete scorers so they register themselves on Scorer.
from jobcaliber.scoring.scorer import LLMScorer, SystemOneScorer, validate_systemone_questions

__all__ = [
    "Evaluator",
    "LLMScorer",
    "Scorer",
    "SystemOneScorer",
    "validate_systemone_questions",
]
