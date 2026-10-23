"""Read config/profile.yaml + config/settings.yaml (or their examples) and the .env file.

`profile.yaml` is what changes the model's answers (search inputs + evaluation rules + criteria);
`settings.yaml` is everything else (scraping, schedule, notifications, ai, paths). Keeping them
apart is what makes "changing the profile re-scores, changing the settings does not" true.
"""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from jobcaliber.core.config import AppConfig
from jobcaliber.infrastructure.env import load_env

CONFIG_DIR = "config"
PROFILE_FILENAMES = ("profile.yaml", "profile.example.yaml")
SETTINGS_FILENAMES = ("settings.yaml", "settings.example.yaml")


class ConfigError(RuntimeError):
    pass


def load_config(root: Path) -> tuple[Path, AppConfig]:
    """Merge both files into one typed config; returns the profile path that keys evaluations."""
    load_env(root)
    folder = root / CONFIG_DIR
    profile_path = _pick(folder, PROFILE_FILENAMES, "profile")
    profile, runtime = _read(profile_path), _read(settings_path(root))
    overlap = sorted(set(profile) & set(runtime))
    if overlap:
        raise ConfigError(
            f"{overlap} declared in both profile and settings; a key belongs to exactly one file"
        )
    merged = {**runtime, **profile}
    config = AppConfig.model_validate(merged)
    validate_timezone(config.schedule.timezone)
    return profile_path, config


def settings_path(root: Path) -> Path:
    return _pick(root / CONFIG_DIR, SETTINGS_FILENAMES, "settings")


def _pick(root: Path, names: tuple[str, ...], what: str) -> Path:
    for name in names:
        candidate = root / name
        if candidate.exists():
            return candidate
    raise ConfigError(f"no {what} file found in {root}: expected one of {[str(root / n) for n in names]}")


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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
