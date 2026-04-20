"""Groq Whisper transcription (whisper-large-v3-turbo, very cheap & fast)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..config import get_api_key


@dataclass
class _Seg:
    start: float
    end: float
    text: str


class GroqWhisper:
    def __init__(self, model: str = "whisper-large-v3-turbo", language: str = "ja", **_: object):
        from groq import Groq
        key = get_api_key("groq")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self.client = Groq(api_key=key)
        self.model = model
        self.language = language

    def transcribe(self, media: Path, log) -> Iterable[_Seg]:
        log(f"  Groq Whisper ({self.model}) にアップロード中…")
        with media.open("rb") as f:
            resp = self.client.audio.transcriptions.create(
                file=(media.name, f.read()),
                model=self.model, language=self.language,
                response_format="verbose_json",
            )
        for s in getattr(resp, "segments", []) or []:
            yield _Seg(start=float(s["start"]), end=float(s["end"]), text=str(s["text"]))
