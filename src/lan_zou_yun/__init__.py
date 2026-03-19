from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
import tomllib

from lan_zou_yun.app_state import get_bundled_base_dir


__all__ = ["get_app_version"]


@lru_cache(maxsize=1)
def get_app_version() -> str:
    pyproject_path = get_bundled_base_dir() / "pyproject.toml"
    if pyproject_path.exists():
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        return data["tool"]["poetry"]["version"]
    try:
        return version("lan-zou-yun")
    except PackageNotFoundError:
        return "0.0.0"
