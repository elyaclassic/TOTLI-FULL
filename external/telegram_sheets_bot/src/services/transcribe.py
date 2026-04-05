"""Ovozni matnga: OpenAI API yoki bepul lokal Whisper (faster-whisper)."""
import asyncio
import io
import logging
from pathlib import Path

import httpx

from src.config import (
    OPENAI_API_KEY,
    TRANSCRIBE_BACKEND,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_LANGUAGE,
    WHISPER_LOCAL_MODEL,
)

logger = logging.getLogger(__name__)

_local_model = None


def _have_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def can_transcribe() -> bool:
    """Ovozni matnga o'tkazish hozir mumkinmi."""
    mode = TRANSCRIBE_BACKEND
    if mode == "openai":
        return bool(OPENAI_API_KEY)
    if mode == "local":
        return _have_faster_whisper()
    # auto
    if OPENAI_API_KEY:
        return True
    return _have_faster_whisper()


def _resolve_backend() -> str:
    """'openai' yoki 'local'."""
    mode = TRANSCRIBE_BACKEND
    if mode == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("TRANSCRIBE_BACKEND=openai uchun OPENAI_API_KEY kerak")
        return "openai"
    if mode == "local":
        if not _have_faster_whisper():
            raise RuntimeError(
                "Lokal (bepul) Whisper uchun: pip install faster-whisper "
                "(birinchi ishga tushirishda model yuklanadi, bir necha daqiqa)"
            )
        return "local"
    # auto
    if OPENAI_API_KEY:
        return "openai"
    if not _have_faster_whisper():
        raise RuntimeError(
            "Bepul variant: pip install faster-whisper va OPENAI_API_KEY ni bo'sh qoldiring. "
            "Yoki OpenAI kaliti qo'shing."
        )
    return "local"


def _get_local_model():
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel

        logger.info(
            "Lokal Whisper yuklanmoqda: model=%s device=%s",
            WHISPER_LOCAL_MODEL,
            WHISPER_DEVICE,
        )
        _local_model = WhisperModel(
            WHISPER_LOCAL_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _local_model


def _transcribe_local_sync(path: Path) -> str:
    model = _get_local_model()
    kwargs = {"beam_size": 5}
    if WHISPER_LANGUAGE:
        kwargs["language"] = WHISPER_LANGUAGE
    segments, _info = model.transcribe(str(path), **kwargs)
    parts = [s.text.strip() for s in segments]
    text = " ".join(parts).strip()
    if not text:
        raise RuntimeError("Transkripsiya bo'sh qaytdi")
    return text


async def _transcribe_openai(path: Path) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY sozlanmagan")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    data: dict = {"model": "whisper-1"}
    if WHISPER_LANGUAGE:
        data["language"] = WHISPER_LANGUAGE

    raw = path.read_bytes()
    buf = io.BytesIO(raw)

    async with httpx.AsyncClient(timeout=120.0) as client:
        files = {"file": (path.name, buf, "application/octet-stream")}
        r = await client.post(url, headers=headers, data=data, files=files)
        r.raise_for_status()
        body = r.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise RuntimeError("Transkripsiya bo'sh qaytdi")
    return text


async def transcribe_audio_file(path: Path) -> str:
    """Tanlangan backend bo'yicha matn qaytaradi."""
    backend = _resolve_backend()
    if backend == "openai":
        return await _transcribe_openai(path)
    return await asyncio.to_thread(_transcribe_local_sync, path)
