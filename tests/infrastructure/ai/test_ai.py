import json
from pathlib import Path

import httpx
import pytest

from jobcaliber.application.clients import AIClients
from jobcaliber.infrastructure.ai import LLMClient, PromptError, PromptStore, SystemOneClient, render
from jobcaliber.core.config import AIConfig, AIEngine

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
ROOT = Path(__file__).resolve().parents[3]


def test_render_replaces_placeholders():
    assert render("Hello {{name}} {{missing}}", {"name": "world"}) == "Hello world {{missing}}"


def test_prompt_store_llm_rejects_text_kind():
    try:
        PromptStore(PROMPTS_DIR).load_llm("nope")
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_prompt_store_missing_file_raises():
    store = PromptStore(PROMPTS_DIR, custom={"scoring": "does_not_exist"})
    try:
        store.load_text("scoring")
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_prompt_store_unknown_kind_raises():
    try:
        PromptStore(PROMPTS_DIR).load_text("nope")
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_system_one_client_requires_system_one_engine():
    engine = AIEngine(kind="llm", api="openai", base_url="x", model="m")
    try:
        SystemOneClient(engine)
        assert False, "expected AIError"
    except Exception:
        pass


def test_ai_client_registry_and_create_dispatch():
    from jobcaliber.infrastructure.ai import AIClient

    assert set(AIClient._registry) == {"systemone", "openai"}
    assert isinstance(AIClient.create(AIEngine(kind="decision", api="systemone", base_url="x", model="m")), SystemOneClient)
    assert isinstance(AIClient.create(AIEngine(kind="llm", api="openai", base_url="x", model="m")), LLMClient)

    try:
        AIClient.create(AIEngine.model_construct(kind="unknown", api="x", base_url="x", model="m"))
        assert False, "expected AIError"
    except Exception:
        pass


def test_llm_client_uses_openai_wire():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    client = LLMClient(
        AIEngine(kind="llm", api="openai", base_url="http://o/v1", model="m", api_key_env="MY_KEY"),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.complete("q") == "hi"
    assert seen["path"] == "/v1/chat/completions"


def test_ai_clients_resolve_roles_and_names(tmp_path):
    ai_config = AIConfig(
        engines={
            "sc": AIEngine(kind="decision", api="systemone", base_url="x", model="m"),
            "ll": AIEngine(kind="llm", api="openai", base_url="x", model="m"),
        },
        roles={"scorer": "ll"},
    )
    clients = AIClients.from_config(ai_config, ROOT)
    assert isinstance(clients.llm("scorer"), LLMClient)
    assert isinstance(clients.by_name("sc"), SystemOneClient)
    with pytest.raises(Exception, match="not a decision engine"):
        clients.system_one("scorer")


def test_ai_clients_validate_criteria_when_building_the_scorer(tmp_path):
    from jobcaliber.core.config import Criterion, Question

    cfg = AIConfig(
        engines={"sc": AIEngine(kind="decision", api="systemone", base_url="x", model="m")},
        roles={"scorer": "sc"},
    )
    clients = AIClients.from_config(cfg, ROOT)
    bad = {"core": Criterion(min_threshold=0.5, question=Question(
        type="choice", instructions="?", options={"a": "a"}, missing="a"))}
    with pytest.raises(ValueError, match="scored criterion needs a 'score' question"):
        clients.scorer(bad)


def test_ai_clients_unknown_role_raises(tmp_path):
    clients = AIClients.from_config(AIConfig(), tmp_path)
    try:
        clients.client("scorer")
        assert False, "expected AIError"
    except Exception:
        pass


def make_criteria():
    from jobcaliber.core.config import Criterion, Question
    return {"core_skills": Criterion(min_threshold=0.5, question=Question(
        type="score", instructions="how good?", levels=["Not stated", "No", "Yes"], missing=0))}


def test_ai_clients_build_scorer_for_both_kinds(tmp_path):
    from jobcaliber.pipeline.scoring import LLMScorer, Scorer, SystemOneScorer

    criteria = make_criteria()

    system_one_cfg = AIConfig(
        engines={"sc": AIEngine(kind="decision", api="systemone", base_url="x", model="m")},
        roles={"scorer": "sc"},
    )
    system_one_scorer = AIClients.from_config(system_one_cfg, ROOT).scorer(criteria)
    assert isinstance(system_one_scorer, SystemOneScorer)
    assert isinstance(system_one_scorer, Scorer)

    llm_cfg = AIConfig(
        engines={"ll": AIEngine(kind="llm", api="openai", base_url="x", model="m")},
        roles={"scorer": "ll"},
    )
    llm_scorer = AIClients.from_config(llm_cfg, ROOT).scorer(criteria)
    assert isinstance(llm_scorer, LLMScorer)
    assert isinstance(llm_scorer, Scorer)


def test_client_merges_configured_headers(monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    engine = AIEngine(
        kind="llm", api="openai", base_url="http://x/v1", model="m",
        api_key_env="MY_KEY", headers={"x-opencode-session": "jobcaliber"},
    )
    client = LLMClient(engine, httpx.Client(transport=httpx.MockTransport(handler)))

    assert client.headers()["Authorization"] == "Bearer secret"
    assert client.headers()["x-opencode-session"] == "jobcaliber"
    assert client.complete("q") == "ok"
    assert seen["x-opencode-session"] == "jobcaliber"


def test_client_without_configured_headers_is_unchanged():
    engine = AIEngine(kind="llm", api="openai", base_url="http://x/v1", model="m")
    client = LLMClient(engine, httpx.Client())
    assert client.headers() == {"Content-Type": "application/json"}


def test_llm_client_sends_configured_options_under_contract_fields():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    engine = AIEngine(
        kind="llm", api="openai", base_url="http://x/v1", model="qwen3:8b",
        options={"reasoning_effort": "none", "max_tokens": 400, "model": "should-not-win"},
    )
    LLMClient(engine, httpx.Client(transport=httpx.MockTransport(handler))).complete("q")

    assert seen["reasoning_effort"] == "none"
    assert seen["max_tokens"] == 400
    assert seen["model"] == "qwen3:8b"


def _retry_client(responses, **engine_kw):
    calls = {"n": 0}
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[index]

    engine = AIEngine(kind="llm", api="openai", base_url="http://x/v1", model="m", **engine_kw)
    client = LLMClient(engine, httpx.Client(transport=httpx.MockTransport(handler)), sleep_fn=sleeps.append)
    return client, calls, sleeps


OK = httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})


def test_post_retries_transient_status_then_succeeds():
    client, calls, sleeps = _retry_client([httpx.Response(429), httpx.Response(503), OK])
    assert client.complete("q") == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_post_gives_up_after_max_attempts():
    client, calls, _ = _retry_client([httpx.Response(429)], retry={"max_attempts": 3, "base_delay_s": 0.01})
    with pytest.raises(httpx.HTTPStatusError):
        client.complete("q")
    assert calls["n"] == 3


def test_post_does_not_retry_a_rejecting_answer():
    client, calls, sleeps = _retry_client([httpx.Response(401)])
    with pytest.raises(httpx.HTTPStatusError):
        client.complete("q")
    assert calls["n"] == 1
    assert sleeps == []


def test_post_honours_retry_after_header():
    client, _, sleeps = _retry_client([httpx.Response(429, headers={"Retry-After": "7"}), OK])
    assert client.complete("q") == "ok"
    assert sleeps == [7.0]


def test_throttle_sleeps_before_every_request():
    client, calls, sleeps = _retry_client([OK], throttle_s=0.5)
    client.complete("q")
    client.complete("q")
    assert calls["n"] == 2
    assert sleeps == [0.5, 0.5]
