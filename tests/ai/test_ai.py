import json
from pathlib import Path

import httpx

from jobcaliber.ai import AIClients, LLMClient, PromptError, PromptStore, SystemOneClient, render
from jobcaliber.config import AIConfig, AIEngine

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
ROOT = Path(__file__).resolve().parents[2]


def test_render_replaces_placeholders():
    assert render("Hello {{name}} {{missing}}", {"name": "world"}) == "Hello world {{missing}}"


def test_prompt_store_loads_json_and_renders():
    store = PromptStore(PROMPTS_DIR)
    questions = store.load_json("scoring_systemone", {"core_skills": "c++ (lvl 5)", "tools": "Qt",
                                                       "seniority": "senior", "contract_type": "permanent",
                                                       "primary_location": "Sardegna"})
    assert questions["core"]["type"] == "score"
    assert "c++ (lvl 5)" in questions["core"]["instructions"]
    assert questions["location"]["criteria"]["primary"].endswith("(Sardegna)")


def test_prompt_store_loads_llm_front_matter():
    system, user = PromptStore(PROMPTS_DIR).load_llm("explainer")
    assert system.startswith("You are a concise")
    assert "{{title}}" in user


def test_prompt_store_llm_rejects_non_llm_kind():
    try:
        PromptStore(PROMPTS_DIR).load_llm("scoring_systemone")
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_prompt_store_missing_file_raises():
    store = PromptStore(PROMPTS_DIR, custom={"explainer": "does_not_exist"})
    try:
        store.load_text("explainer")
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
    from jobcaliber.ai import AIClient

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
        roles={"scorer": "sc", "explainer": "ll"},
    )
    clients = AIClients.from_config(ai_config, ROOT)
    assert isinstance(clients.system_one("scorer"), SystemOneClient)
    assert isinstance(clients.llm("explainer"), LLMClient)
    assert isinstance(clients.by_name("sc"), SystemOneClient)


def test_ai_clients_validate_scorer_prompt(tmp_path):
    pdir = tmp_path / "prompts" / "scoring_systemone"
    pdir.mkdir(parents=True)
    (pdir / "default.json").write_text(json.dumps({
        "core": {"type": "score", "criteria": ["a", "b"]},
        "tools": {"type": "score", "criteria": ["a", "b"]},
        "contract": {"type": "score", "criteria": ["a", "b"]},
        "pay": {"type": "score", "criteria": ["low", "Not stated"]},
        "location": {"type": "choice", "criteria": {"primary": "x", "remote": "x"}},
    }), encoding="utf-8")
    cfg = AIConfig(
        engines={"sc": AIEngine(kind="decision", api="systemone", base_url="x", model="m")},
        roles={"scorer": "sc"},
    )
    try:
        AIClients.from_config(cfg, tmp_path)
        assert False, "expected PromptError"
    except PromptError:
        pass


def test_ai_clients_unknown_role_raises(tmp_path):
    clients = AIClients.from_config(AIConfig(), tmp_path)
    try:
        clients.client("scorer")
        assert False, "expected AIError"
    except Exception:
        pass


def test_ai_clients_build_scorer_for_both_kinds(tmp_path):
    from jobcaliber.config import LocationPrefs, Profile, Skills
    from jobcaliber.scoring import LLMScorer, Scorer, SystemOneScorer

    profile = Profile(titles=["Dev"], skills=Skills(core={"c++": 5}), location=LocationPrefs(primary="Sardegna"))

    system_one_cfg = AIConfig(
        engines={"sc": AIEngine(kind="decision", api="systemone", base_url="x", model="m")},
        roles={"scorer": "sc"},
    )
    system_one_scorer = AIClients.from_config(system_one_cfg, ROOT).scorer(profile)
    assert isinstance(system_one_scorer, SystemOneScorer)
    assert isinstance(system_one_scorer, Scorer)

    llm_cfg = AIConfig(
        engines={"ll": AIEngine(kind="llm", api="openai", base_url="x", model="m")},
        roles={"scorer": "ll"},
    )
    llm_scorer = AIClients.from_config(llm_cfg, ROOT).scorer(profile)
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
