"""Local faster-whisper transcription (GPU/CPU/MPS)."""
from __future__ import annotations

import sys
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
        with LocalWhisper._models_lock:
            platform_io.add_cuda_dll_dirs()
            from faster_whisper import WhisperModel

            attempts = self._attempts()
            first_err: Exception | None = None
            for device, ctype in attempts:
                key = (self.model_name, device, ctype)
                cached = LocalWhisper._models.get(key)
                if cached is not None:
                    return cached
                try:
                    log(f"  faster-whisper {self.model_name} on {device}/{ctype} を起動…")
                    model = WhisperModel(self.model_name, device=device, compute_type=ctype)
                    LocalWhisper._models[key] = model
                    return model
                except Exception as e:
                    first_err = e
                    log(f"  {device}/{ctype} 起動失敗 ({type(e).__name__})")
                    continue
            raise RuntimeError(f"faster-whisper の起動に失敗: {first_err}")

    def _attempts(self) -> list[tuple[str, str]]:
        """Ordered (device, compute_type) attempts. For device='auto' we try
        the best accelerator first, then fall back on failure.
        faster-whisper uses ctranslate2, not torch, so we don't probe with
        torch — we just let ct2 tell us what works."""
        if self.device != "auto":
            return [(self.device, self.compute_type)]
        if sys.platform == "darwin":
            # No CUDA on Mac; CT2 has no Metal backend → int8 on CPU is fastest.
            return [("cpu", "int8")]
        # Windows / Linux: try CUDA first, fall back to CPU int8.
        return [("cuda", "float16"), ("cpu", "int8")]

    def transcribe(self, media: Path, log) -> Iterable[_Seg]:
        model = self._load(log)
        log("  文字起こし中…")
        segments, _info = model.transcribe(
            str(media), language=self.language,
            vad_filter=self.vad_filter, beam_size=self.beam_size,
        )
        for s in segments:
            yield _Seg(start=s.start, end=s.end, text=s.text)
