"""Transcription providers: local faster-whisper, OpenAI Whisper API, Groq."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Protocol

Logger = Callable[[str], None]


class Segment(Protocol):
    start: float
    end: float
    text: str


class Transcriber(Protocol):
    def transcribe(self, media: Path, log: Logger) -> Iterable[Segment]: ...


def get(provider: str, settings: dict) -> Transcriber:
    if provider == "local":
        from .local import LocalWhisper
        return LocalWhisper(**settings)
    if provider == "openai":
        from .openai_api import OpenAIWhisper
        return OpenAIWhisper(**settings)
    if provider == "groq":
        from .groq_api import GroqWhisper
        return GroqWhisper(**settings)
    raise ValueError(f"Unknown transcribe provider: {provider}")


def write_outputs(segments: Iterable[Segment], dst_dir: Path) -> tuple[Path, Path]:
    """Write transcript.txt + transcript.srt atomically (.tmp then rename),
    so an interruption mid-write does not leave a half-finished file that
    later runs would skip."""
    txt = dst_dir / "transcript.txt"
    srt = dst_dir / "transcript.srt"
    txt_tmp = txt.with_suffix(".txt.tmp")
    srt_tmp = srt.with_suffix(".srt.tmp")
    try:
        with txt_tmp.open("w", encoding="utf-8") as ft, srt_tmp.open("w", encoding="utf-8") as fs:
            for i, seg in enumerate(segments, 1):
                line = seg.text.strip()
                ft.write(line + "\n")
                fs.write(f"{i}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{line}\n\n")
        txt_tmp.replace(txt)
        srt_tmp.replace(srt)
    finally:
        for p in (txt_tmp, srt_tmp):
            if p.exists():
                p.unlink(missing_ok=True)
    return txt, srt


def _ts(s: float) -> str:
    h = int(s // 3600); s -= h * 3600
    m = int(s // 60);   s -= m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
