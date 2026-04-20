"""OS abstractions: paths, subprocess flags, opening folders."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# subprocess creation flag to suppress console window on Windows
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def user_config_dir(app: str) -> Path:
    """Return per-OS user config directory for `app` (created if missing)."""
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif IS_MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / app
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_cache_dir(app: str) -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif IS_MACOS:
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / app
    d.mkdir(parents=True, exist_ok=True)
    return d


def open_folder(path: Path) -> None:
    """Reveal a folder in the OS file manager."""
    p = str(path)
    if IS_WINDOWS:
        os.startfile(p)  # type: ignore[attr-defined]
    elif IS_MACOS:
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def add_cuda_dll_dirs() -> None:
    """On Windows + Python, ensure pip-installed nvidia-* DLLs are loadable.
    Safe no-op elsewhere."""
    if not IS_WINDOWS:
        return
    import importlib.util

    extra: list[str] = []
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
        spec = importlib.util.find_spec(pkg)
        if not spec or not spec.submodule_search_locations:
            continue
        bin_dir = os.path.join(spec.submodule_search_locations[0], "bin")
        if os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)  # type: ignore[attr-defined]
            extra.append(bin_dir)
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra) + os.pathsep + os.environ.get("PATH", "")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run wrapper that hides console window on Windows."""
    kwargs.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(cmd, **kwargs)
