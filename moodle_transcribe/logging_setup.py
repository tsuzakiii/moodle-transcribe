"""Persistent logging to ~/.cache/moodle-transcribe/log/YYYY-MM-DD.log.

Returns a `Logger` callable that writes to both file and an optional GUI sink.
File logs are appended across runs so you can grep them later.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from . import platform_io

GuiSink = Callable[[str], None]


def make_logger(gui_sink: GuiSink | None = None) -> Callable[[str], None]:
    log_dir = platform_io.user_cache_dir("moodle-transcribe") / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    def log(msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts}  {msg}"
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if gui_sink:
            gui_sink(line)
        else:
            print(line, flush=True)
    return log
