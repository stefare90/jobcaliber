"""Read config.yaml (or the example) and the .env file. The only place that touches the disk."""
from __future__ import annotations

from pathlib import Path

import yaml

from jobcaliber.core.config import AppConfig
from jobcaliber.infrastructure.env import load_env

CONFIG_FILENAME = "config.yaml"
EXAMPLE_FILENAME = "config.example.yaml"


def load_config(root: Path) -> tuple[Path, AppConfig]:
    load_env(root)
    path = root / CONFIG_FILENAME
    if not path.exists():
        path = root / EXAMPLE_FILENAME
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return path, AppConfig.model_validate(raw)
