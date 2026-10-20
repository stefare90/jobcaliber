import pytest

from jobcaliber.config import (
    AppConfig,
    Criterion,
    GateAccept,
    GateMinScore,
    Question,
)
from jobcaliber.models import GateDecision, ScoringResult
from jobcaliber.scoring import Evaluator

SCALE = ["No correlation", "Not verifiable", "Partial", "Full"]


def score_q(levels=SCALE, missing=1):
    return Question(type="score", instructions="?", levels=list(levels), missing=missing)


def bool_q():
    return Question(type="choice", instructions="?", options={"yes": "y", "no": "n", "missing": "m"}, missing="missing")


def choice_q(options=("accepted", "rejected", "unknown"), missing="unknown"):
    return Question(type="choice", instructions="?", options={o: o for o in options}, missing=missing)


def criteria_default():
    return {
        "core_skills": Criterion(min_threshold=0.5, apply_threshold=1.0, question=score_q()),
        "role_fit": Criterion(apply_threshold=1.0, question=score_q()),
        "location": Criterion(gate=GateAccept(accept=["accepted"]), question=choice_q()),
        "contract_ok": Criterion(gate=True, question=bool_q()),
    }


def make_config(criteria=None, penalties=None, min_conf=0.55):
    criteria = criteria or criteria_default()
    return AppConfig.model_validate({
        "search": {"titles": ["Dev"], "on_site_locations": ["Turin, Italy"]},
        "criteria": {k: v.model_dump() for k, v in criteria.items()},
        "penalties": penalties or {},
        "notifications": {"telegram": {"min_confidence": min_conf}},
    })


def result(core=1.0, role=1.0, location="accepted", contract="yes", missing=(), confidence=0.9):
    return ScoringResult(
        answers={"core_skills": core, "role_fit": role, "location": location, "contract_ok": contract},
        missing=set(missing), confidence=confidence,
    )


def test_all_criteria_above_apply_threshold_passes():
    ev = Evaluator(make_config()).evaluate(result())
    assert ev.decision == GateDecision.PASS
    assert ev.score_total == pytest.approx(100.0)
    assert ev.dropped_by is None


def test_below_min_threshold_drops_with_the_reason():
    ev = Evaluator(make_config()).evaluate(result(core=0.0))
    assert ev.decision == GateDecision.DROP
    assert ev.dropped_by == "core_skills"
    assert "min_threshold" in ev.reasons[0]


def test_between_min_and_apply_goes_to_review():
    ev = Evaluator(make_config()).evaluate(result(core=0.67))
    assert ev.decision == GateDecision.REVIEW
    assert any("apply_threshold" in r for r in ev.reasons)


def test_not_verifiable_forces_review_and_never_drops():
    ev = Evaluator(make_config()).evaluate(result(core=0.5, missing={"core_skills"}))
    assert ev.decision == GateDecision.REVIEW
    assert ev.dropped_by is None
    assert any("not verifiable" in r for r in ev.reasons)


def test_missing_answer_applies_the_confidence_penalty():
    cfg = make_config(penalties={"core_skills": 0.8})
    ev = Evaluator(cfg).evaluate(result(missing={"core_skills"}, confidence=1.0))
    assert ev.confidence == pytest.approx(0.8)


def test_gate_drops_before_any_threshold():
    ev = Evaluator(make_config()).evaluate(result(location="rejected"))
    assert ev.decision == GateDecision.DROP
    assert ev.dropped_by == "location"


def test_gate_never_drops_a_missing_answer():
    ev = Evaluator(make_config()).evaluate(result(location="unknown", missing={"location"}))
    assert ev.decision == GateDecision.REVIEW


def test_boolean_gate_requires_yes():
    assert Evaluator(make_config()).evaluate(result(contract="no")).dropped_by == "contract_ok"
    assert Evaluator(make_config()).evaluate(result(contract="missing", missing={"contract_ok"})).decision == GateDecision.REVIEW


def test_min_score_gate_drops_below_threshold():
    criteria = {
        "core_skills": Criterion(apply_threshold=1.0, question=score_q()),
        "strict": Criterion(gate=GateMinScore(min_score=0.8), question=score_q()),
    }
    cfg = make_config(criteria)
    assert Evaluator(cfg).evaluate(
        ScoringResult(answers={"core_skills": 1.0, "strict": 0.67}, confidence=0.9)
    ).dropped_by == "strict"
    assert Evaluator(cfg).evaluate(
        ScoringResult(answers={"core_skills": 1.0, "strict": 1.0}, confidence=0.9)
    ).decision == GateDecision.PASS


def test_criterion_without_apply_threshold_does_not_block_pass():
    criteria = {
        "core_skills": Criterion(apply_threshold=1.0, question=score_q()),
        "notes": Criterion(min_threshold=0.0, question=score_q()),
    }
    ev = Evaluator(make_config(criteria)).evaluate(
        ScoringResult(answers={"core_skills": 1.0, "notes": 0.0}, confidence=0.9)
    )
    assert ev.decision == GateDecision.PASS


def test_low_confidence_never_passes():
    ev = Evaluator(make_config(min_conf=0.95)).evaluate(result(confidence=0.6))
    assert ev.decision == GateDecision.REVIEW


def test_scores_are_the_mean_of_scored_criteria():
    ev = Evaluator(make_config()).evaluate(result(core=0.67, role=1.0))
    assert ev.score_total == pytest.approx(round((0.67 + 1.0) / 2 * 100, 1))
    assert set(ev.sub_scores) == {"core_skills", "role_fit"}
