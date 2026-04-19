"""Local speech recognition via faster-whisper (no cloud API)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

_model: WhisperModel | None = None
_model_lock = threading.Lock()


def _build_model() -> WhisperModel:
    from faster_whisper import WhisperModel

    s = get_settings()
    root = (s.whisper_download_root or "").strip() or None
    return WhisperModel(
        s.whisper_model_size,
        device=s.whisper_device,
        compute_type=s.whisper_compute_type,
        download_root=root,
    )


def get_whisper_model() -> WhisperModel:
    global _model
    with _model_lock:
        if _model is None:
            _model = _build_model()
        return _model


def transcribe_audio_file(path: str) -> str:
    model = get_whisper_model()
    segments, _info = model.transcribe(
        path,
        beam_size=5,
        vad_filter=True,
    )
    parts: list[str] = []
    for seg in segments:
        t = (seg.text or "").strip()
        if t:
            parts.append(t)
    return " ".join(parts).strip()
