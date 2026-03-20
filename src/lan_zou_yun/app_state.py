import json
from pathlib import Path
import sys
from typing import Any
import tomllib


APP_EXE_NAME = "lan_zou_zip_tool_gui.exe"
APP_CONFIG_NAME = "lan_zou_zip_tool_gui.json"
GITHUB_REPO = "AutumnPizazz/lan-zou-yun-zip-tool"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"
DEFAULT_CONFIG = {
    "ui": {
        "last_page": "split",
        "window_width": 760,
        "window_height": 620,
        "font_scale": 1.0,
    },
    "split": {
        "last_source_path": "",
        "last_output_dir": "",
        "part_size_mb": 49,
    },
    "restore": {
        "last_manifest_path": "",
        "last_save_dir": "",
        "last_extract_dir": "",
    },
}

FONT_SCALE_MIN_DEFAULT = 0.8
FONT_SCALE_MAX_DEFAULT = 2.2
FONT_SCALE_STEP_DEFAULT = 0.1


def get_runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_bundled_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


def get_config_path() -> Path:
    return get_runtime_base_dir() / APP_CONFIG_NAME


def _load_ui_toml_settings() -> dict[str, Any]:
    bundled_dir = get_bundled_base_dir()
    runtime_dir = get_runtime_base_dir()
    if getattr(sys, "frozen", False):
        candidates = [bundled_dir / "pyproject.toml"]
    else:
        candidates = [runtime_dir / "pyproject.toml"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        tool = data.get("tool") if isinstance(data, dict) else None
        if not isinstance(tool, dict):
            continue
        section = tool.get("lan_zou_gui")
        if isinstance(section, dict):
            return section
    return {}


def get_font_scale_limits() -> tuple[float, float, float]:
    settings = _load_ui_toml_settings()
    try:
        min_scale = float(settings.get("font_scale_min", FONT_SCALE_MIN_DEFAULT))
    except (TypeError, ValueError):
        min_scale = FONT_SCALE_MIN_DEFAULT
    try:
        max_scale = float(settings.get("font_scale_max", FONT_SCALE_MAX_DEFAULT))
    except (TypeError, ValueError):
        max_scale = FONT_SCALE_MAX_DEFAULT
    try:
        step = float(settings.get("font_scale_step", FONT_SCALE_STEP_DEFAULT))
    except (TypeError, ValueError):
        step = FONT_SCALE_STEP_DEFAULT
    if step <= 0:
        step = FONT_SCALE_STEP_DEFAULT
    if min_scale <= 0:
        min_scale = FONT_SCALE_MIN_DEFAULT
    if max_scale <= 0:
        max_scale = FONT_SCALE_MAX_DEFAULT
    if min_scale > max_scale:
        min_scale, max_scale = max_scale, min_scale
    return min_scale, max_scale, step


def merge_defaults(data: Any, defaults: Any) -> Any:
    if isinstance(defaults, dict):
        result = {}
        data = data if isinstance(data, dict) else {}
        for key, default_value in defaults.items():
            result[key] = merge_defaults(data.get(key), default_value)
        return result
    return data if data is not None else defaults


class AppConfig:
    def __init__(self):
        self.path = get_config_path()
        self.data = merge_defaults({}, DEFAULT_CONFIG)

    def load(self) -> None:
        if not self.path.exists():
            self.data = merge_defaults({}, DEFAULT_CONFIG)
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError):
            self.data = merge_defaults({}, DEFAULT_CONFIG)
            return
        self.data = merge_defaults(loaded, DEFAULT_CONFIG)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self.data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def set(self, *keys: str, value: Any) -> None:
        current = self.data
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = value


__all__ = [
    "APP_CONFIG_NAME",
    "APP_EXE_NAME",
    "AppConfig",
    "DEFAULT_CONFIG",
    "FONT_SCALE_MAX_DEFAULT",
    "FONT_SCALE_MIN_DEFAULT",
    "FONT_SCALE_STEP_DEFAULT",
    "GITHUB_REPO",
    "LATEST_RELEASE_API",
    "RELEASES_PAGE_URL",
    "get_font_scale_limits",
    "get_bundled_base_dir",
    "get_config_path",
    "get_runtime_base_dir",
]
