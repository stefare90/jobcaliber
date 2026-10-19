import pytest

from jobcaliber.config import (
    AppConfig,
    FilterParam,
    JobFilters,
    LocationFilter,
    LocationPrefs,
    Notifications,
    PayFilter,
    Profile,
    TelegramNotifications,
)
from jobcaliber.scoring.evaluator import Evaluator
from jobcaliber.models import GateDecision, LocationBucket, SystemOneResult


@pytest.fixture
def config():
    return AppConfig(
        profile=Profile(titles=["Software Engineer"], location=LocationPrefs(primary="Sardegna")),
        job_filters=JobFilters(
            core_skills=FilterParam(weight=45),
            tools=FilterParam(weight=20),
            contract=FilterParam(weight=20),
            pay=PayFilter(mode="hybrid", weight=15),
            location=LocationFilter(mode="hard_gate", weight=0),
        ),
        notifications=Notifications(telegram=TelegramNotifications(
            notify_threshold=70, review_threshold=60, min_confidence=0.55)),
    )


def test_evaluator_drops_elsewhere_on_hard_gate(config):
    s1 = SystemOneResult(core_score=1.0, tools_score=1.0, contract_score=1.0, pay_score=1.0,
                         pay_missing=False, location_bucket=LocationBucket.ELSEWHERE, confidence=0.9)
    res = Evaluator(config).evaluate(s1)
    assert res.decision == GateDecision.DROP
    assert res.score_total == 0.0


def test_evaluator_drops_critically_low_pay(config):
    s1 = SystemOneResult(core_score=1.0, tools_score=1.0, contract_score=1.0, pay_score=0.0,
                         pay_missing=False, location_bucket=LocationBucket.PRIMARY, confidence=0.9)
    res = Evaluator(config).evaluate(s1)
    assert res.decision == GateDecision.DROP


def test_evaluator_passes_good_posting(config):
    s1 = SystemOneResult(core_score=0.9, tools_score=0.8, contract_score=1.0, pay_score=0.66,
                         pay_missing=False, location_bucket=LocationBucket.PRIMARY, confidence=0.95)
    res = Evaluator(config).evaluate(s1)
    assert res.decision == GateDecision.PASS
    assert res.score_total >= 70


def test_evaluator_routes_uncertain_to_review(config):
    s1 = SystemOneResult(core_score=0.8, tools_score=0.7, contract_score=0.8, pay_score=0.33,
                         pay_missing=True, location_bucket=LocationBucket.UNKNOWN, confidence=0.6)
    res = Evaluator(config).evaluate(s1)
    assert res.decision == GateDecision.REVIEW
