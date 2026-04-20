"""Local faster-whisper transcription (GPU/CPU/MPS)."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .. import platform_io


@dataclass
class _Seg:
    start: float
    end: float
    text: str


class LocalWhisper:
    # Process-wide cache keyed by (model, device, compute_type) so that
    # changing config doesn't keep using the first-loaded combination.
    _models: dict[tuple[str, str, str], object] = {}
    _models_lock = threading.Lock()

    def __init__(self, model: str = "large-v3", device: str = "auto",
                 compute_type: str = "float16", language: str = "ja",
                 beam_size: int = 5, vad_filter: bool = True, **_: object):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.vad_filter = vad_filter

    def _load(self, log):
        device, ctype = self._pick_device_and_ctype()
        key = (self.model_name, device, ctype)
        with LocalWhisper._models_lock:
            cached = LocalWhisper._models.get(key)
            if cached is not None:
                return cached
            platform_io.add_cuda_dll_dirs()
            from faster_whisper import WhisperModel
            try:
                log(f"  faster-whisper {self.model_name} on {device}/{ctype} を起動…")
                model = WhisperModel(self.model_name, device=device, compute_type=ctype)
            except Exception as e:
                log(f"  起動失敗 ({e}) → CPU int8 にフォールバック")
                key = (self.model_name, "cpu", "int8")
                model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            LocalWhisper._models[key] = model
            return model

    def _pick_device_and_ctype(self) -> tuple[str, str]:
        if self.device != "auto":
            return self.device, self.compute_type
        # auto: try cuda, then mps (mac), else cpu
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda", "float16"
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                return "cpu", "int8"  # ct2 lacks proper MPS; cpu int8 is the practical choice on Mac
        except ImportError:
            pass
        return "cpu", "int8"

    def transcribe(self, media: Path, log) -> Iterable[_Seg]:
        model = self._load(log)
        log("  文字起こし中…")
        segments, _info = model.transcribe(
            str(media), language=self.language,
            vad_filter=self.vad_filter, beam_size=self.beam_size,
        )
        for s in segments:
            yield _Seg(start=s.start, end=s.end, text=s.text)
