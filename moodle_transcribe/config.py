"""Configuration loader: TOML file + environment variable overrides."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from . import platform_io

DEFAULT_CONFIG: dict[str, Any] = {
    "output_dir": "~/moodle_out",
    "cookies_file": None,  # filled in below per-OS
    "transcribe": {
        "provider": "local",
        "local": {
            "model": "large-v3",
            "device": "auto",
            "compute_type": "float16",
            "language": "ja",
            "beam_size": 5,
            "vad_filter": True,
        },
        "openai": {"model": "whisper-1", "language": "ja"},
        "groq": {"model": "whisper-large-v3-turbo", "language": "ja"},
    },
    "llm": {
        "provider": "claude_cli",
        "claude_cli": {
            "model": "haiku",
            "scratch_dir": "~/.cache/moodle-transcribe/_routing_scratch",
        },
        "anthropic": {"model": "claude-haiku-4-5"},
        "openai": {"model": "gpt-5-mini"},
    },
    "moodle": {
        "host": "wsdmoodle.waseda.jp",
        "login_check_url": "https://wsdmoodle.waseda.jp/my/",
    },
    "gui": {"playwright_headless": True},
}


@dataclass
class Config:
    output_dir: Path
    cookies_file: Path
    transcribe: dict[str, Any]
    llm: dict[str, Any]
    moodle: dict[str, Any]
    gui: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)

    @property
    def transcribe_provider(self) -> str:
        return self.transcribe["provider"]

    @property
    def llm_provider(self) -> str:
        return self.llm["provider"]


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _resolve_path(p: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(p)))).resolve()


def default_config_path() -> Path:
    return platform_io.user_config_dir("moodle-transcribe") / "config.toml"


def default_cookies_path() -> Path:
    return platform_io.user_config_dir("moodle-transcribe") / "moodle_cookies.txt"


def _resolve_relative_to(base: Path, p: str | Path) -> Path:
    """Expand ~ and env vars; if still relative, anchor to `base` (the config
    file's directory) instead of the current working directory."""
    expanded = Path(os.path.expandvars(os.path.expanduser(str(p))))
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def load(path: Path | None = None) -> Config:
    """Load config from TOML, falling back to defaults. Env vars override paths."""
    cfg = dict(DEFAULT_CONFIG)
    cfg["cookies_file"] = str(default_cookies_path())

    env_path = os.environ.get("MOODLE_TRANSCRIBE_CONFIG")
    if env_path:
        env_path = os.path.expandvars(os.path.expanduser(env_path))
    chosen = path or Path(env_path) if env_path else (path or default_config_path())
    if chosen.exists():
        with chosen.open("rb") as f:
            user_cfg = tomllib.load(f)
        cfg = _deep_merge(cfg, user_cfg)

    # Env var overrides for common knobs
    if env_out := os.environ.get("MOODLE_TRANSCRIBE_OUTPUT_DIR"):
        cfg["output_dir"] = env_out
    if env_cookies := os.environ.get("MOODLE_TRANSCRIBE_COOKIES"):
        cfg["cookies_file"] = env_cookies

    base = chosen.parent if chosen.exists() else Path.cwd()
    return Config(
        output_dir=_resolve_relative_to(base, cfg["output_dir"]),
        cookies_file=_resolve_relative_to(base, cfg["cookies_file"]),
        transcribe=cfg["transcribe"],
        llm=cfg["llm"],
        moodle=cfg["moodle"],
        gui=cfg["gui"],
        raw=cfg,
    )


def get_api_key(provider: str) -> str | None:
    """Look up API key from env. Provider in {openai, anthropic, groq}."""
    return os.environ.get(f"{provider.upper()}_API_KEY")
