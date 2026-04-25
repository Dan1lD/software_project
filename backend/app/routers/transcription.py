from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from app.services.local_whisper import transcribe_audio_file
from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/speech", tags=["speech"])
log = logging.getLogger(__name__)


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict[str, str]:
    suffix = Path(audio.filename or "voice.oga").suffix or ".oga"
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:

        def _run() -> str:
            return transcribe_audio_file(tmp_path)

        text = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("Whisper transcription failed")
        raise HTTPException(
            status_code=503,
            detail=f"Speech transcription failed: {e!s}",
        ) from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {"text": text.strip()}
