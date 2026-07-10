from pathlib import Path
import tomllib

import krystal_quorum


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["version"] == "0.7.0"
    assert krystal_quorum.__version__ == pyproject["project"]["version"]
