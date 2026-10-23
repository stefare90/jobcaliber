from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from jobcaliber.infrastructure.config_loader import load_config
from jobcaliber.core.config import (
    AIConfig,
    AIEngine,
    AppConfig,
    Criterion,
    GateAccept,
    Question,
    Search,
)

FULL_YAML = """
db_path: "./data/jobs.db"
search:
  titles: ["Software Engineer"]
  on_site_locations: ["Sardinia, Italy"]
  remote_locations: ["Italy"]
  exclude: ["tirocini"]
criteria:
  core_skills:
    min_threshold: 0.5
    apply_threshold: 1.0
    question:
      type: "score"
      instructions: "how well do the skills match?"
      levels: ["Not stated", "No match", "Good", "Perfect"]
      missing: 0
  location:
    gate: {accept: ["primary", "remote"]}
    question:
      type: "choice"
      instructions: "which arrangement?"
      options: {primary: "onsite", remote: "remote", unknown: "unknown"}
      missing: "unknown"
penalties: {core_skills: 0.85}
notifications:
  telegram: {notify_threshold: 70, review_threshold: 60, min_confidence: 0.55}
schedule:
  timezone: "Europe/Rome"
scraping:
  boards: ["linkedin", "indeed"]
  board_max_results: {linkedin: 300, indeed: 500}
ai:
  engines:
    rizzo: {kind: "decision", api: "systemone", base_url: "http://127.0.0.1:8017", model: "rizzo-latest"}
    local_llm: {kind: "llm", api: "openai", base_url: "http://localhost:11434/v1", model: "qwen3:8b"}
  roles: {scorer: "rizzo"}
  custom_prompts: {}
"""


def test_app_config_parses_full_yaml():
    cfg = AppConfig.model_validate(yaml.safe_load(FULL_YAML))
    assert cfg.search.titles == ["Software Engineer"]
    assert cfg.search.on_site_locations == ["Sardinia, Italy"]
    assert cfg.search.remote_locations == ["Italy"]
    assert cfg.search.exclude == ["tirocini"]
    assert cfg.criteria["core_skills"].min_threshold == 0.5
    assert isinstance(cfg.criteria["location"].gate, GateAccept)
    assert cfg.penalties == {"core_skills": 0.85}
    assert cfg.ai.engines["rizzo"].kind == "decision"
    assert cfg.ai.roles["scorer"] == "rizzo"


def test_app_config_defaults():
    cfg = AppConfig.model_validate({
        "search": {"titles": ["Dev"], "on_site_locations": ["Turin, Italy"]},
        "schedule": {"timezone": "UTC"},
        "criteria": {"core": {"min_threshold": 0.5, "question": {
            "type": "score", "instructions": "?", "levels": ["a", "b"], "missing": 0}}},
    })
    assert cfg.penalties == {}
    assert cfg.ai.engines == {}
    assert cfg.scraping.max_results("linkedin") == 300


def test_app_config_rejects_unknown_top_level_key():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({
            "search": {"titles": ["Dev"], "on_site_locations": ["Turin, Italy"]},
            "schedule": {"timezone": "UTC"},
        "schedule": {"timezone": "UTC"},
            "criteria": {"core": {"min_threshold": 0.5, "question": {
                "type": "score", "instructions": "?", "levels": ["a", "b"], "missing": 0}}},
            "job_filters": {"core_skills": {"weight": 45}},
        })


def test_app_config_rejects_invalid_criteria():
    with pytest.raises(ValidationError, match="set a gate or at least one threshold"):
        AppConfig.model_validate({
            "search": {"titles": ["Dev"], "on_site_locations": ["Turin, Italy"]},
            "schedule": {"timezone": "UTC"},
        "schedule": {"timezone": "UTC"},
            "criteria": {"core": {"question": {
                "type": "score", "instructions": "?", "levels": ["a", "b"], "missing": 0}}},
        })


def test_board_max_results_rejects_unknown_board():
    with pytest.raises(ValidationError, match="board_max_results names unknown boards"):
        AppConfig.model_validate({
            "search": {"titles": ["Dev"], "on_site_locations": ["Turin, Italy"]},
            "schedule": {"timezone": "UTC"},
        "schedule": {"timezone": "UTC"},
            "criteria": {"core": {"min_threshold": 0.5, "question": {
                "type": "score", "instructions": "?", "levels": ["a", "b"], "missing": 0}}},
            "scraping": {"boards": ["linkedin"], "board_max_results": {"linkedin": 300, "indeed": 500}},
        })


def test_engine_kind_api_validation():
    AIEngine(kind="llm", api="openai", base_url="http://x", model="m")
    with pytest.raises(ValidationError, match="unknown engine kind"):
        AIEngine(kind="system_one", api="openai", base_url="x", model="m")
    with pytest.raises(ValidationError, match="not valid for kind"):
        AIEngine(kind="llm", api="systemone", base_url="x", model="m")


def test_engine_options_rejected_outside_llm_kind():
    with pytest.raises(ValueError, match="'options' is only valid for kind 'llm'"):
        AIEngine(kind="decision", api="systemone", base_url="x", model="m", options={"seed": 1})


def test_engine_resolves_api_key_from_env(monkeypatch):
    monkeypatch.setenv("MY_KEY", "from-env")
    assert AIEngine(kind="decision", api="systemone", base_url="x", model="m",
                    api_key_env="MY_KEY").resolve_api_key() == "from-env"
    monkeypatch.delenv("MY_KEY")
    assert AIEngine(kind="decision", api="systemone", base_url="x", model="m",
                    api_key_env="MY_KEY").resolve_api_key() == ""


def test_roles_reject_unknown_role_and_engine():
    with pytest.raises(ValidationError, match="unknown role 'explainer'"):
        AIConfig(
            engines={"sc": AIEngine(kind="decision", api="systemone", base_url="x", model="m")},
            roles={"scorer": "sc", "explainer": "sc"},
        )
    with pytest.raises(ValidationError, match="references unknown engine"):
        AIConfig(engines={}, roles={"scorer": "ghost"})


def test_load_config_prefers_personal_file(tmp_path):
    example = tmp_path / "config.example.yaml"
    example.write_text(FULL_YAML, encoding="utf-8")
    path, cfg = load_config(tmp_path)
    assert path.name == "config.example.yaml"
    (tmp_path / "config.yaml").write_text(FULL_YAML, encoding="utf-8")
    path, _ = load_config(tmp_path)
    assert path.name == "config.yaml"


def test_schedule_timezone_is_required():
    base = {
        "search": {"titles": ["Dev"], "on_site_locations": ["Turin, Italy"]},
        "criteria": {"core": {"min_threshold": 0.5, "question": {
            "type": "score", "instructions": "?", "levels": ["a", "b"], "missing": 0}}},
    }
    with pytest.raises(ValidationError, match="timezone"):
        AppConfig.model_validate({**base, "schedule": {}})


def test_load_config_rejects_an_unknown_zone(tmp_path):
    from jobcaliber.infrastructure.config_loader import ConfigError, load_config

    source = (Path(__file__).resolve().parents[2] / "config.example.yaml").read_text(encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        source.replace('timezone: "Europe/Rome"', 'timezone: "Europe/Roma"'), encoding="utf-8")
    with pytest.raises(ConfigError, match="not an IANA zone"):
        load_config(tmp_path)
