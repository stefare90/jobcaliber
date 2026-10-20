import json

import httpx
import pytest

from jobcaliber.ai import LLMClient, PromptStore, SystemOneClient
from jobcaliber.config import AIEngine, Criterion, GateAccept, Question
from jobcaliber.models import GateDecision, JobPosting, ScoringResult
from jobcaliber.scoring import Evaluator, LLMScorer, Scorer, SystemOneScorer
from jobcaliber.scoring.scorer.system_one import validate_answers


def score_q(levels=("Not stated", "No match", "Weak", "Good", "Perfect"), missing=0):
    return Question(type="score", instructions="how good?", levels=list(levels), missing=missing)


def choice_q(options=("yes", "no", "missing"), missing="missing"):
    return Question(type="choice", instructions="ok?", options={o: o for o in options}, missing=missing)


def make_criteria() -> dict[str, Criterion]:
    return {
        "core_skills": Criterion(weight=45, question=score_q()),
        "tools": Criterion(weight=20, question=score_q()),
        "salary_ok": Criterion(gate=True, question=choice_q()),
    }


POSTING = JobPosting(
    external_id="1", url="http://x", title="Embedded Engineer", company="Acme",
    source="linkedin", location_raw="Cagliari", description="C++ firmware role.",
)


def systemone_client(answers: dict) -> SystemOneClient:
    payload = {"answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    return SystemOneClient(AIEngine(kind="decision", api="systemone", base_url="http://mock", model="m"), http)


def test_systemone_scorer_maps_levels_and_choices():
    client = systemone_client({
        "core_skills": {"type": "score", "score": 4, "confidence": 0.9},
        "tools": {"type": "score", "score": 2, "confidence": 0.8},
        "salary_ok": {"type": "choice", "choice": "yes", "confidence": 0.9},
    })
    result = SystemOneScorer(client, make_criteria()).score_posting(POSTING)
    assert result.answers["core_skills"] == pytest.approx(1.0)
    assert result.answers["tools"] == pytest.approx(0.5)
    assert result.answers["salary_ok"] == "yes"
    assert result.missing == set()
    assert result.confidence == pytest.approx(0.866, abs=1e-3)


def test_systemone_scorer_flags_missing_and_keeps_neutral_score():
    client = systemone_client({
        "core_skills": {"type": "score", "score": 0},
        "tools": {"type": "score", "score": 3},
        "salary_ok": {"type": "choice", "choice": "missing"},
    })
    result = SystemOneScorer(client, make_criteria()).score_posting(POSTING)
    assert result.missing == {"core_skills", "salary_ok"}
    assert result.answers["core_skills"] == 0.5
    assert result.answers["tools"] == pytest.approx(0.75)


def llm_client(content: str, capture: dict) -> LLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        capture.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return LLMClient(
        AIEngine(kind="llm", api="openai", base_url="http://mock/v1", model="m"),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_llm_scorer_parses_keys_and_missing_list():
    capture: dict = {}
    content = json.dumps({
        "core_skills": 0.9, "tools": 0.4, "salary_ok": "yes",
        "missing": ["tools"], "confidence": 0.7, "summary_reason": "good",
    })
    client = llm_client(content, capture)
    result = LLMScorer(client, make_criteria()).score_posting(POSTING)
    assert result.answers["core_skills"] == pytest.approx(0.9)
    assert result.answers["tools"] == 0.5
    assert result.missing == {"tools"}
    assert result.answers["salary_ok"] == "yes"
    assert result.confidence == pytest.approx(0.7)
    assert "Embedded Engineer" in capture["messages"][-1]["content"]


def test_scorer_registry_dispatches_by_engine_kind():
    assert set(Scorer._registry) == {"decision", "llm"}
    assert Scorer._registry["decision"] is SystemOneScorer
    assert Scorer._registry["llm"] is LLMScorer
    with pytest.raises(Exception, match="no scorer registered"):
        Scorer.create(type("C", (), {"engine": AIEngine.model_construct(kind="ghost")})(), make_criteria(), None)


def test_validate_answers_rejects_mismatched_criteria():
    client = systemone_client({})
    with pytest.raises(Exception, match="do not match criteria"):
        validate_answers({"other": {}}, make_criteria())
    scorer = SystemOneScorer(client, make_criteria())
    assert set(scorer.questions) == set(make_criteria())


def test_systemone_projection_matches_criteria_shape():
    scorer = SystemOneScorer(systemone_client({}), make_criteria())
    assert scorer.questions["core_skills"]["type"] == "score"
    assert scorer.criteria["core_skills"].question.missing == 0
    assert scorer.criteria["salary_ok"].question.missing == "missing"


def test_scorer_rejects_invalid_criteria_at_construction():
    with pytest.raises(ValueError, match="set either weight > 0 or a gate"):
        SystemOneScorer(systemone_client({}), {"x": Criterion(question=score_q())})
