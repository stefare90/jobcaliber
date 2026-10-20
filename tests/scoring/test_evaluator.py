import pytest

from jobcaliber.config import (
    AppConfig,
    Criterion,
    GateAccept,
    GateMinScore,
    Question,
    TelegramNotifications,
)
from jobcaliber.models import GateDecision, ScoringResult
from jobcaliber.scoring import Evaluator


def score_q(levels=("Not stated", "No match", "Good", "Perfect"), missing=0):
    return Question(type="score", instructions="?", levels=list(levels), missing=missing)


def bool_q():
    return Question(type="choice", instructions="?", options={"yes": "y", "no": "n", "missing": "m"}, missing="missing")


def choice_q(options=("primary", "remote", "hybrid", "elsewhere", "unknown"), missing="unknown"):
    return Question(type="choice", instructions="?", options={o: o for o in options}, missing=missing)


def make_config(criteria=None, penalties=None, notify=70.0, review=60.0, min_conf=0.55) -> AppConfig:
    criteria = criteria or {
        "core_skills": Criterion(weight=45, question=score_q()),
        "tools": Criterion(weight=20, question=score_q()),
        "contract": Criterion(weight=20, question=score_q()),
        "pay": Criterion(weight=15, question=score_q()),
        "location": Criterion(gate=GateAccept(accept=["primary", "remote", "hybrid"]), question=choice_q()),
    }
    return AppConfig.model_validate({
        "search": {"titles": ["Dev"], "locations": [{"query": "Turin, Italy"}]},
        "criteria": {k: v.model_dump() for k, v in criteria.items()},
        "penalties": penalties or {},
        "notifications": {"telegram": {
            "notify_threshold": notify, "review_threshold": review, "min_confidence": min_conf,
        }},
    })


def result(answers, missing=(), confidence=0.9):
    return ScoringResult(answers=answers, missing=set(missing), confidence=confidence)


def happy_answers(**over):
    answers = {"core_skills": 0.9, "tools": 0.8, "contract": 0.9, "pay": 0.7, "location": "primary"}
    answers.update(over)
    return answers


def test_weighted_sum_normalizes_by_total_weight():
    ev = Evaluator(make_config()).evaluate(result(happy_answers()))
    expected = (45 * 0.9 + 20 * 0.8 + 20 * 0.9 + 15 * 0.7) / 100 * 100
    assert ev.score_total == pytest.approx(round(expected, 1))
    assert ev.decision == GateDecision.PASS
    assert ev.dropped_by is None
    assert set(ev.sub_scores) == {"core_skills", "tools", "contract", "pay"}


def test_accept_gate_drops_outside_the_accepted_options():
    ev = Evaluator(make_config()).evaluate(result(happy_answers(location="elsewhere")))
    assert ev.decision == GateDecision.DROP
    assert ev.dropped_by == "location"
    assert ev.score_total == 0.0


def test_gate_never_drops_a_missing_answer():
    ev = Evaluator(make_config()).evaluate(result(happy_answers(location="unknown"), missing={"location"}))
    assert ev.decision != GateDecision.DROP
    assert ev.dropped_by is None


def test_boolean_gate_requires_yes():
    criteria = {
        "core_skills": Criterion(weight=45, question=score_q()),
        "salary_ok": Criterion(gate=True, question=bool_q()),
    }
    ev_true = Evaluator(make_config(criteria)).evaluate(result({"core_skills": 0.8, "salary_ok": "yes"}))
    assert ev_true.decision == GateDecision.PASS
    ev_false = Evaluator(make_config(criteria)).evaluate(result({"core_skills": 0.8, "salary_ok": "no"}))
    assert ev_false.dropped_by == "salary_ok"
    ev_missing = Evaluator(make_config(criteria)).evaluate(
        result({"core_skills": 0.8, "salary_ok": "missing"}, missing={"salary_ok"})
    )
    assert ev_missing.decision != GateDecision.DROP


def test_min_score_gate_drops_below_threshold():
    criteria = {
        "core_skills": Criterion(weight=45, question=score_q()),
        "strict": Criterion(gate=GateMinScore(min_score=0.8), question=score_q()),
    }
    ev = Evaluator(make_config(criteria)).evaluate(result({"core_skills": 0.9, "strict": 0.5}))
    assert ev.dropped_by == "strict"
    ok = Evaluator(make_config(criteria)).evaluate(result({"core_skills": 0.9, "strict": 0.85}))
    assert ok.decision == GateDecision.PASS


def test_missing_answer_lowers_confidence_and_forces_review():
    criteria = {
        "core_skills": Criterion(weight=45, question=score_q()),
        "pay": Criterion(weight=55, question=score_q()),
    }
    cfg = make_config(criteria, penalties={"pay": 0.85})
    ev = Evaluator(cfg).evaluate(result({"core_skills": 1.0, "pay": 0.5}, missing={"pay"}, confidence=1.0))
    assert ev.confidence == pytest.approx(0.85)
    assert ev.decision == GateDecision.REVIEW
    assert any("not stated" in r for r in ev.reasons)


def test_thresholds_route_pass_review_drop():
    cfg = make_config(notify=90.0, review=80.0)
    assert Evaluator(cfg).evaluate(result(happy_answers())).decision == GateDecision.REVIEW
    cfg_low = make_config(notify=95.0, review=95.0)
    assert Evaluator(cfg_low).evaluate(result(happy_answers())).decision == GateDecision.DROP


def test_low_confidence_never_passes():
    cfg = make_config(min_conf=0.95)
    ev = Evaluator(cfg).evaluate(result(happy_answers(), confidence=0.6))
    assert ev.decision == GateDecision.REVIEW


def test_missing_data_on_a_weighted_criterion_uses_neutral_score():
    criteria = {
        "core_skills": Criterion(weight=50, question=score_q()),
        "pay": Criterion(weight=50, question=score_q()),
    }
    ev = Evaluator(make_config(criteria)).evaluate(result({"core_skills": 1.0, "pay": 0.5}, missing={"pay"}))
    assert ev.sub_scores["pay"] == 0.5
    assert ev.score_total == pytest.approx(75.0)


def test_config_without_weighted_criteria_is_rejected():
    cfg = make_config({"location": Criterion(gate=GateAccept(accept=["primary"]), question=choice_q())})
    with pytest.raises(ValueError, match="no weighted criterion"):
        Evaluator(cfg).evaluate(result({"location": "primary"}))
