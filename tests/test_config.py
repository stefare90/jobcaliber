import pytest
from pydantic import ValidationError

from jobcaliber.config import AIConfig, AIEngine, AppConfig, JobFilters, LocationFilter, load_config

FULL_YAML = """
version: 9
db_path: "./data/jobs.db"
profile:
  titles: ["Software Engineer"]
  seniority: "senior"
  contract_type: "permanent"
  skills:
    core: { "c++": 5 }
    tools: ["Qt"]
  location: { primary: "Sardegna", remote_ok: true, hybrid_max_km: 40 }
job_filters:
  core_skills: { mode: "weighted", weight: 45 }
  pay: { mode: "hybrid", weight: 15, target_annual: 40000, min_annual: 38000, hard_drop_tolerance: 0.05 }
  location: { mode: "hard_gate", weight: 0 }
notifications:
  telegram: { notify_threshold: 70, review_threshold: 60, min_confidence: 0.55 }
scraping:
  boards: ["linkedin", "indeed"]
  hours_old: null
  extra_searches: [{ keywords: "Backend Developer", location: "Italy" }]
ai:
  engines:
    rizzo: { kind: "decision", api: "systemone", base_url: "http://127.0.0.1:8017", model: "rizzo-latest" }
    local_llm: { kind: "llm", api: "openai", base_url: "http://localhost:11434/v1", model: "gpt-oss:20b" }
  roles: { scorer: "rizzo", explainer: "local_llm" }
  custom_prompts: { explainer: "concise_it" }
"""


def test_app_config_parses_full_yaml():
    import yaml
    cfg = AppConfig.model_validate(yaml.safe_load(FULL_YAML))
    assert cfg.version == 9
    assert cfg.profile.location.primary == "Sardegna"
    assert cfg.job_filters.pay.min_annual == 38000
    assert cfg.scraping.extra_searches[0].keywords == "Backend Developer"
    assert cfg.ai.engines["rizzo"].kind == "decision"
    assert cfg.ai.roles["scorer"] == "rizzo"
    assert cfg.ai.custom_prompts["explainer"] == "concise_it"


def test_app_config_defaults():
    cfg = AppConfig.model_validate({"profile": {"titles": ["Dev"], "location": {"primary": "Torino"}}})
    assert cfg.job_filters.core_skills.weight == 45
    assert cfg.ai.engines == {}
    assert cfg.ai.roles == {}
    assert cfg.ai.prompts_dir == "prompts"


def test_app_config_requires_profile():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"version": 9})


def test_engine_rejects_bad_api_for_kind():
    with pytest.raises(ValidationError):
        AIEngine(kind="decision", api="openai", base_url="x", model="m")
    with pytest.raises(ValidationError):
        AIEngine(kind="llm", api="systemone", base_url="x", model="m")


def test_ai_config_rejects_role_with_unknown_engine():
    with pytest.raises(ValidationError):
        AIConfig(
            engines={"rizzo": AIEngine(kind="decision", api="systemone", base_url="x", model="m")},
            roles={"scorer": "missing"},
        )


def test_ai_config_rejects_role_kind_mismatch():
    with pytest.raises(ValidationError):
        AIConfig(
            engines={"sc": AIEngine(kind="decision", api="systemone", base_url="x", model="m")},
            roles={"explainer": "sc"},
        )


def test_ai_config_allows_llm_scorer():
    cfg = AIConfig(
        engines={"ll": AIEngine(kind="llm", api="openai", base_url="x", model="m")},
        roles={"scorer": "ll"},
    )
    assert cfg.roles["scorer"] == "ll"


def test_location_bucket_scores_must_match_enum():
    with pytest.raises(ValidationError):
        LocationFilter(bucket_scores={"primary": 1.0, "remote": 1.0})
    with pytest.raises(ValidationError):
        LocationFilter(bucket_scores={"primary": 1.0, "remote": 1.0, "hybrid": 0.8,
                                      "unknown": 0.5, "elsewhere": 0.0, "extra": 0.1})
    JobFilters(location=LocationFilter(bucket_scores={"primary": 1.0, "remote": 1.0, "hybrid": 0.8,
                                                      "unknown": 0.5, "elsewhere": 0.0}))


def test_engine_resolves_api_key_from_env(monkeypatch):
    monkeypatch.setenv("MY_KEY", "from-env")
    assert AIEngine(kind="decision", api="systemone", base_url="x", model="m", api_key_env="MY_KEY").resolve_api_key() == "from-env"
    monkeypatch.delenv("MY_KEY")
    assert AIEngine(kind="decision", api="systemone", base_url="x", model="m", api_key_env="MY_KEY").resolve_api_key() == ""


def test_load_config_prefers_personal_copy(tmp_path):
    (tmp_path / "config.example.yaml").write_text("profile:\n  titles: [A]\n  location: {primary: X}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("profile:\n  titles: [B]\n  location: {primary: Y}\n", encoding="utf-8")
    path, cfg = load_config(tmp_path)
    assert path.name == "config.yaml"
    assert cfg.profile.titles == ["B"]


def test_load_config_falls_back_to_example(tmp_path):
    (tmp_path / "config.example.yaml").write_text("profile:\n  titles: [A]\n  location: {primary: X}\n", encoding="utf-8")
    path, cfg = load_config(tmp_path)
    assert path.name == "config.example.yaml"
    assert cfg.profile.location.primary == "X"
