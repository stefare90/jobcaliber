import os
from pathlib import Path

import pytest

from jobcaliber.core.config import load_config
from jobcaliber.core.env import ENV_FILENAME, EnvFileError, load_env, parse_env

ROOT = Path(__file__).resolve().parents[2]


def test_parse_env_handles_comments_quotes_and_export():
    values = parse_env(
        "\n".join(
            [
                "# comment",
                "",
                "PLAIN=value",
                'export EXPORTED="quoted value"',
                "SINGLE='single'",
                "EQUALS=a=b",
                "  SPACED = padded  ",
            ]
        )
    )
    assert values == {
        "PLAIN": "value",
        "EXPORTED": "quoted value",
        "SINGLE": "single",
        "EQUALS": "a=b",
        "SPACED": "padded",
    }


def test_parse_env_rejects_malformed_lines():
    with pytest.raises(EnvFileError, match=r":2: expected KEY=VALUE"):
        parse_env("GOOD=1\nnot an assignment\n", source=".env")


def test_load_env_file_does_not_override_real_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ALREADY_SET", "from-env")
    monkeypatch.delenv("FROM_FILE", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("ALREADY_SET=from-file\nFROM_FILE=file-value\n", encoding="utf-8")

    load_env(tmp_path)

    assert os.environ["ALREADY_SET"] == "from-env"
    assert os.environ["FROM_FILE"] == "file-value"


def test_load_env_without_file_is_a_noop(tmp_path):
    assert load_env(tmp_path) == {}


def test_load_config_reads_root_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    (tmp_path / ENV_FILENAME).write_text("OPENCODE_API_KEY=oc_sk_from_dotenv\n", encoding="utf-8")
    source = ROOT / "config.example.yaml"
    (tmp_path / "config.example.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    _, cfg = load_config(tmp_path)

    assert cfg.ai.engines["jev"].resolve_api_key() == "oc_sk_from_dotenv"
