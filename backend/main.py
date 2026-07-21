"""
FastAPI application — TTS Web Backend.

Endpoints:
  POST /api/tts     — Convert text to a single MP3 file.
  GET  /api/voices  — List available voices for a given language.
"""

import json
import base64
import asyncio
import logging
import os
import shutil
import tempfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from services.tts_service import (
    detect_language,
    get_voices_for_language,
    process_text_to_speech,
)
from services.audio_merge import merge_audio_chunks

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TTS Web Backend",
    description="Converts long text into a single downloadable MP3 using edge-tts.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all: return a clean JSON error instead of a stack trace."""
    logger.exception("Unhandled error for %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

MAX_TEXT_BYTES = 46 * 1024  # 46 KB

class TTSRequest(BaseModel):
    """Body for POST /api/tts."""
    text: str = Field(..., min_length=1, description="The text to convert to speech.")
    voice_name: str = Field(
        ...,
        min_length=1,
        description="edge-tts voice ShortName, e.g. 'en-US-GuyNeural'.",
    )


class VoiceInfo(BaseModel):
    short_name: str
    gender: str
    locale: str


class VoicesResponse(BaseModel):
    language: str
    voices: list[VoiceInfo]


class LanguageDetectionRequest(BaseModel):
    """Body for POST /api/detect-language."""
    text: str = Field(..., min_length=1, description="Text to detect the language of.")


class LanguageDetectionResponse(BaseModel):
    language: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/api/tts",
    response_class=StreamingResponse,
    summary="Convert text to MP3 with real-time progress streaming",
    responses={
        200: {
            "content": {"application/x-ndjson": {}},
            "description": "Stream of JSON progress events followed by final audio payload.",
        },
        400: {"description": "Invalid input."},
        500: {"description": "TTS or merge failure."},
    },
)
async def text_to_speech(body: TTSRequest):
    """
    Accept text + voice name, generate speech with real-time progress updates,
    and return NDJSON stream containing progress events and final base64 MP3.
    """
    # --- Validate size ---
    if len(body.text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Text exceeds maximum allowed size of {MAX_TEXT_BYTES // 1024} KB.",
        )

    async def event_generator():
        temp_dir = tempfile.mkdtemp(prefix="tts_chunks_")
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def push_progress(pct: int, status: str):
            queue.put_nowait({"type": "progress", "percent": pct, "status": status})

        push_progress(5, "Analyzing text…")

        async def run_pipeline():
            try:
                logger.info(
                    "TTS request — voice=%s, text_length=%d chars",
                    body.voice_name,
                    len(body.text),
                )

                chunk_paths = await process_text_to_speech(
                    text=body.text,
                    voice=body.voice_name,
                    temp_dir=temp_dir,
                    on_progress=push_progress,
                )

                push_progress(92, "Merging audio chunks…")
                audio_buffer = merge_audio_chunks(chunk_paths)

                audio_bytes = audio_buffer.getvalue()
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

                push_progress(100, "Done!")
                queue.put_nowait({"type": "complete", "audio_base64": audio_b64})
            except ValueError as exc:
                queue.put_nowait({"type": "error", "detail": str(exc)})
            except Exception:
                logger.exception("TTS processing failed")
                queue.put_nowait({
                    "type": "error",
                    "detail": "Text-to-speech generation failed. Please try again.",
                })
            finally:
                queue.put_nowait(None)

        asyncio.create_task(run_pipeline())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield json.dumps(item) + "\n"
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")



@app.get(
    "/api/voices",
    response_model=VoicesResponse,
    summary="List available voices for a language",
    responses={
        200: {"description": "Voice list for requested language."},
        404: {"description": "No voices found for this language."},
    },
)
async def list_voices(language: str):
    """
    Return available edge-tts voices for the given language code.

    *language* can be a 2-letter code (e.g. ``en``) or a full locale
    (e.g. ``en-US``).
    """
    if not language or not language.strip():
        raise HTTPException(status_code=400, detail="Language parameter is required.")

    voices = await get_voices_for_language(language.strip())

    if not voices:
        raise HTTPException(
            status_code=404,
            detail=f"No voices found for language '{language}'.",
        )

    return VoicesResponse(language=language.strip(), voices=voices)


@app.post(
    "/api/detect-language",
    response_model=LanguageDetectionResponse,
    summary="Detect the language of provided text",
    responses={
        200: {"description": "Detected language locale code."},
        400: {"description": "Language could not be detected."},
    },
)
async def detect_language_endpoint(body: LanguageDetectionRequest):
    """
    Detect the language of the provided text and return the best-matching
    edge-tts locale code (e.g. ``en-US``).
    """
    try:
        locale = detect_language(body.text)
        return LanguageDetectionResponse(language=locale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/health", summary="Health check")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
