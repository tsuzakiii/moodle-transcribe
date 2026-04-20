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
    """Write transcript.txt + transcript.srt; return their paths."""
    txt = dst_dir / "transcript.txt"
    srt = dst_dir / "transcript.srt"
    with txt.open("w", encoding="utf-8") as ft, srt.open("w", encoding="utf-8") as fs:
        for i, seg in enumerate(segments, 1):
            line = seg.text.strip()
            ft.write(line + "\n")
            fs.write(f"{i}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{line}\n\n")
    return txt, srt


def _ts(s: float) -> str:
    h = int(s // 3600); s -= h * 3600
    m = int(s // 60);   s -= m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
