"""Read config.yaml (or the example) and the .env file. The only place that touches the disk."""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from jobcaliber.core.config import AppConfig
from jobcaliber.infrastructure.env import load_env

CONFIG_FILENAME = "config.yaml"
EXAMPLE_FILENAME = "config.example.yaml"


class ConfigError(RuntimeError):
    pass


def load_config(root: Path) -> tuple[Path, AppConfig]:
    load_env(root)
    path = root / CONFIG_FILENAME
    if not path.exists():
        path = root / EXAMPLE_FILENAME
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(raw)
    validate_timezone(config.schedule.timezone)
    return path, config


def validate_timezone(name: str) -> str:
    """Fail fast on a typo: an unknown zone would silently shift every scheduled run."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(
            f"schedule.timezone {name!r} is not an IANA zone name; expected e.g. "
            f"'Europe/Rome', 'Europe/London', 'UTC'"
        ) from None
    return name
