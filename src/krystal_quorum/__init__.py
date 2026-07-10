from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


_VERSION_FALLBACK = "0.7.0"


def _read_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.exists():
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = payload.get("project", {})
        if isinstance(project, dict) and isinstance(project.get("version"), str):
            return project["version"]
    try:
        return version("krystal-quorum")
    except PackageNotFoundError:
        return _VERSION_FALLBACK


__version__ = _read_version()
