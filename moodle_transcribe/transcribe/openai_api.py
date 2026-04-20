"""OpenAI Whisper API transcription."""
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


class OpenAIWhisper:
    def __init__(self, model: str = "whisper-1", language: str = "ja", **_: object):
        from openai import OpenAI
        key = get_api_key("openai")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=key)
        self.model = model
        self.language = language

    def transcribe(self, media: Path, log) -> Iterable[_Seg]:
        log(f"  OpenAI Whisper API ({self.model}) にアップロード中…")
        with media.open("rb") as f:
            resp = self.client.audio.transcriptions.create(
                model=self.model, file=f, language=self.language,
                response_format="verbose_json", timestamp_granularities=["segment"],
            )
        for s in getattr(resp, "segments", []) or []:
            yield _Seg(start=float(s["start"]), end=float(s["end"]), text=str(s["text"]))
