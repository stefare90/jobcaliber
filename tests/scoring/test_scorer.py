import json
from pathlib import Path

import httpx

from jobcaliber.ai import AIError, LLMClient, PromptError, PromptStore, SystemOneClient
from jobcaliber.config import AIEngine, LocationPrefs, Profile, Skills
from jobcaliber.models import JobPosting, LocationBucket
from jobcaliber.scoring import LLMScorer, Scorer, SystemOneScorer, validate_systemone_questions

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def make_profile():
    return Profile(
        titles=["Senior C++ Developer"],
        seniority="senior",
        skills=Skills(core={"c++": 5, "python": 4}, tools=["Qt", "CMake"]),
        location=LocationPrefs(primary="Sardegna"),
    )


def test_system_one_scorer_parses_answers():
    posting = JobPosting(
        external_id="123", url="http://test.com", title="Senior C++ Developer",
        company="Inpeco", location_raw="Cagliari, Italy",
        description="Looking for C++ and Qt expert.", source="linkedin",
    )
    mock_json = {"answers": {
        "core": {"score": 3.0, "confidence": 0.95},
        "tools": {"score": 3.0, "confidence": 0.9},
        "contract": {"score": 2.0, "confidence": 0.85},
        "pay": {"score": 1.0, "confidence": 0.8},
        "location": {"choice": "primary", "confidence": 0.95},
    }}
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=mock_json)))
    client = SystemOneClient(AIEngine(kind="decision", api="systemone", base_url="http://mock", model="m"), http)

    result = SystemOneScorer(client, make_profile(), PromptStore(PROMPTS_DIR)).score_posting(posting)
    assert result.core_score == 1.0
    assert result.tools_score == 1.0
    assert result.contract_score == 1.0
    assert result.pay_missing is True
    assert result.location_bucket == LocationBucket.PRIMARY
    assert result.confidence >= 0.85


def _valid_questions():
    return {
        "core": {"type": "score", "criteria": ["a", "b"]},
        "tools": {"type": "score", "criteria": ["a", "b"]},
        "contract": {"type": "score", "criteria": ["a", "b"]},
        "pay": {"type": "score", "criteria": ["low", "Not stated", "ok"]},
        "location": {"type": "choice", "criteria": {b.value: "x" for b in LocationBucket}},
    }


def test_validate_systemone_questions_accepts_valid():
    validate_systemone_questions(_valid_questions())


def test_validate_systemone_questions_rejects_missing_bucket():
    q = _valid_questions()
    del q["location"]["criteria"]["hybrid"]
    try:
        validate_systemone_questions(q)
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_validate_systemone_questions_rejects_unknown_bucket():
    q = _valid_questions()
    q["location"]["criteria"]["onsite_moon"] = "x"
    try:
        validate_systemone_questions(q)
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_validate_systemone_questions_requires_not_stated_pay():
    q = _valid_questions()
    q["pay"]["criteria"] = ["low", "mid", "high"]
    try:
        validate_systemone_questions(q)
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_scorer_registry_and_create_dispatch():
    from jobcaliber.scoring import Scorer

    assert set(Scorer._registry) == {"decision", "llm"}
    assert Scorer._registry["decision"] is SystemOneScorer
    assert Scorer._registry["llm"] is LLMScorer

    # Unknown engine kind fails with a clear error.
    class _FakeEngine:
        kind = "deterministic"

    class _FakeClient:
        engine = _FakeEngine()

    try:
        Scorer.create(_FakeClient(), make_profile(), PromptStore(PROMPTS_DIR))
        assert False, "expected AIError"
    except AIError:
        pass


def test_llm_scorer_parses_json_response():
    posting = JobPosting(
        external_id="9", url="http://test", title="Embedded Engineer", company="Acme",
        location_raw="Cagliari", description="C++ firmware role.", source="linkedin",
    )
    llm_json = (
        '{"core_score": 0.9, "tools_score": 0.4, "contract_score": 1.0, "pay_score": 0.5, '
        '"pay_missing": true, "location_bucket": "hybrid", "confidence": 0.7, '
        '"summary_reason": "good core match"}'
    )
    payload = {"choices": [{"message": {"content": llm_json}}]}
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    client = LLMClient(AIEngine(kind="llm", api="openai", base_url="http://mock", model="m"), http)

    result = LLMScorer(client, make_profile(), PromptStore(PROMPTS_DIR)).score_posting(posting)
    assert result.core_score == 0.9
    assert result.tools_score == 0.4
    assert result.contract_score == 1.0
    assert result.pay_missing is True
    assert result.location_bucket == LocationBucket.HYBRID
    assert result.summary_reason == "good core match"


def test_system_one_scorer_derives_levels_from_prompt(tmp_path):
    # A custom prompt with 5 core levels must normalize score/4, not score/3.
    pdir = tmp_path / "prompts" / "scoring_systemone"
    pdir.mkdir(parents=True)
    (pdir / "default.json").write_text(json.dumps({
        "core": {"type": "score", "instructions": "x", "criteria": ["a", "b", "c", "d", "e"]},
        "tools": {"type": "score", "instructions": "x", "criteria": ["a", "b"]},
        "contract": {"type": "score", "instructions": "x", "criteria": ["a", "b"]},
        "pay": {"type": "score", "instructions": "x", "criteria": ["low", "Not stated", "ok"]},
        "location": {"type": "choice", "instructions": "x",
                     "criteria": {b.value: "x" for b in LocationBucket}},
    }), encoding="utf-8")

    posting = JobPosting(external_id="1", url="u", title="t", company="c", source="s")
    answers = {"answers": {"core": {"score": 4.0}, "pay": {"score": 1.0}}}
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=answers)))
    client = SystemOneClient(AIEngine(kind="decision", api="systemone", base_url="http://mock", model="m"), http)

    result = SystemOneScorer(client, make_profile(), PromptStore(tmp_path / "prompts")).score_posting(posting)
    assert result.core_score == 1.0
    assert result.pay_missing is True
    assert result.tools_score == 0.5
