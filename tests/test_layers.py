"""The layering is a rule, not a convention: these tests fail when it is broken."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "jobcaliber"
LOWER_LAYERS = ("core", "pipeline", "infrastructure", "application")


def files(*parts: str) -> list[Path]:
    return [p for p in (SRC.joinpath(*parts)).rglob("*.py") if "__pycache__" not in p.parts]


def test_no_lower_layer_imports_entrypoints():
    offenders = [
        f"{path.relative_to(SRC)}: {line.strip()}"
        for layer in LOWER_LAYERS
        for path in files(layer)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "jobcaliber.entrypoints" in line and line.strip().startswith(("import ", "from "))
    ]
    assert offenders == [], f"layers must not import entrypoints: {offenders}"


def test_core_is_free_of_io_and_frameworks():
    forbidden = ("import fastapi", "from fastapi", "import sqlite3", "import httpx", "from httpx")
    offenders = [
        f"{path.relative_to(SRC)}: {line.strip()}"
        for path in files("core")
        for line in path.read_text(encoding="utf-8").splitlines()
        if any(line.strip().startswith(token) for token in forbidden)
    ]
    assert offenders == [], f"core must stay pure: {offenders}"


def test_core_does_not_import_other_layers():
    offenders = [
        f"{path.relative_to(SRC)}: {line.strip()}"
        for path in files("core")
        for line in path.read_text(encoding="utf-8").splitlines()
        if "jobcaliber." in line and line.strip().startswith(("import ", "from "))
        and not line.strip().startswith(("from jobcaliber.core", "import jobcaliber.core"))
    ]
    assert offenders == [], f"core must not depend on other layers: {offenders}"


def test_infrastructure_does_not_import_application_or_entrypoints():
    offenders = [
        f"{path.relative_to(SRC)}: {line.strip()}"
        for path in files("infrastructure")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
        and ("jobcaliber.application" in line or "jobcaliber.entrypoints" in line or "jobcaliber.pipeline" in line)
    ]
    assert offenders == [], f"infrastructure must not depend upwards: {offenders}"


def test_core_reads_no_files():
    """Loading config and .env is I/O: it belongs to infrastructure, not to the models."""
    forbidden = ("import yaml", "from yaml", "open(", "read_text(")
    offenders = [
        f"{path.relative_to(SRC)}: {line.strip()}"
        for path in files("core")
        for line in path.read_text(encoding="utf-8").splitlines()
        if any(token in line for token in forbidden)
    ]
    assert offenders == [], f"core must not touch the filesystem: {offenders}"


def test_entrypoints_are_one_module_each():
    """Three processes, three entry points: cli, worker, web (web added with the web app)."""
    names = {path.name for path in (SRC / "entrypoints").iterdir() if path.is_dir() or path.suffix == ".py"}
    assert {"cli.py", "worker.py"} <= names
