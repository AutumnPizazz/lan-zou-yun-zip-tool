from functools import lru_cache
from pathlib import Path
import tomllib


__all__ = ["get_app_version"]


@lru_cache(maxsize=1)
def get_app_version():
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    return data["tool"]["poetry"]["version"]
