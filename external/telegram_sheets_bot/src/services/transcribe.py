"""OpenAI Whisper API — ovozni matnga."""
import io
from pathlib import Path

import httpx

from src.config import OPENAI_API_KEY, WHISPER_LANGUAGE


async def transcribe_audio_file(path: Path) -> str:
    """path — .ogg / m4a va hokazo."""
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
