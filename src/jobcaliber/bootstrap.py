"""Composition root: the only place that builds the object graph used by every process."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from jobcaliber.core.config import AppConfig
from jobcaliber.infrastructure.config_loader import load_config, settings_path
from jobcaliber.application.clients import AIClients
from jobcaliber.infrastructure.database import Store


@dataclass
class AppContext:
    root: Path
    config_path: Path
    settings_path: Path
    config: AppConfig
    raw_yaml: str
    store: Store
    engine: str
    tz: ZoneInfo

    def scorer(self, engine: str | None = None):
        name = engine or self.engine
        clients = AIClients.from_config(self.config.ai, self.root)
        return clients.scorer_for(name, self.config.criteria, self.config.search.render_values())


def build_context(root: Path, engine: str | None = None, store: Store | None = None) -> AppContext:
    root = Path(root).resolve()
    config_path, config = load_config(root)
    name = engine or config.ai.roles.get("scorer")
    if not name or name not in config.ai.engines:
        raise ValueError(f"unknown scorer engine {name!r}; configured: {sorted(config.ai.engines)}")
    return AppContext(
        root=root,
        config_path=config_path,
        settings_path=settings_path(root),
        config=config,
        raw_yaml=config_path.read_text(encoding="utf-8"),
        store=store or Store(_db_path(root, config)),
        engine=name,
        tz=ZoneInfo(config.schedule.timezone),
    )


def _db_path(root: Path, config: AppConfig) -> Path:
    path = Path(config.db_path)
    return path if path.is_absolute() else root / path
