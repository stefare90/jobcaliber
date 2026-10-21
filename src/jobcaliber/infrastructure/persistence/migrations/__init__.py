"""Ordered schema migrations. One module per version, append-only, never edited after release.

Each module exposes `VERSION` (the version it produces) and `up(conn)`. The last VERSION must
equal `SCHEMA_VERSION`: this is asserted on import so a forgotten bump fails immediately.
"""
from __future__ import annotations

from jobcaliber.infrastructure.persistence.schema_version import SCHEMA_VERSION

MIGRATIONS: list = []

versions = [module.VERSION for module in MIGRATIONS]
assert versions == sorted(set(versions)), f"migrations must be unique and ordered, got {versions}"
assert not versions or versions[-1] == SCHEMA_VERSION, (
    f"SCHEMA_VERSION is {SCHEMA_VERSION} but the latest migration produces {versions[-1]}"
)

__all__ = ["MIGRATIONS", "SCHEMA_VERSION"]
