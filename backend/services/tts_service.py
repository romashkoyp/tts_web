"""
TTS Service — text chunking, edge-tts orchestration, language detection, voice listing.

Adapted from audiobook.py.
"""

import asyncio
import logging
import os
import random
import re
import time
from typing import Any, Callable

import edge_tts
from langdetect import DetectorFactory, LangDetectException, detect

# Ensure deterministic language detection across requests
DetectorFactory.seed = 0

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
WORDS_PER_MINUTE = 150
# ~350 words (~2.3 mins of audio) balances parallel speedup, fast progress updates,
# and low retry cost without excessive WebSocket connection overhead.
MAX_WORDS_PER_CHUNK = int(os.getenv("MAX_WORDS_PER_CHUNK", "350"))
MIN_FILE_SIZE = 1024  # bytes — valid MP3 is at least ~1 KB

# Concurrency controls:
# GLOBAL_MAX_WORKERS caps total simultaneous WebSockets to Microsoft across ALL users.
# PER_REQUEST_MAX_WORKERS prevents a single user from starving other concurrent users.
GLOBAL_MAX_WORKERS = int(os.getenv("GLOBAL_MAX_TTS_WORKERS", "12"))
PER_REQUEST_MAX_WORKERS = int(os.getenv("PER_REQUEST_MAX_TTS_WORKERS", "6"))
MAX_RETRIES = 4

# Maximum characters needed for statistically reliable language identification
LANG_DETECT_SAMPLE_CHARS = 1000

# Pre-compiled regular expressions for text chunking
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bSt)(?<!\bProf)(?<!\bMrs)"
    r"(?<=[.!?\u2026])\s+(?=[^\s\da-z])"
)
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[;,])\s+|\s+(?=[—–]\s)")

# Global concurrency semaphore across all requests
_GLOBAL_SEMAPHORE: asyncio.Semaphore | None = None
_GLOBAL_SEMAPHORE_LOOP: asyncio.AbstractEventLoop | None = None


def _get_global_semaphore() -> asyncio.Semaphore:
    """Lazily initialize the global semaphore on the active event loop."""
    global _GLOBAL_SEMAPHORE, _GLOBAL_SEMAPHORE_LOOP
    current_loop = asyncio.get_running_loop()
    if _GLOBAL_SEMAPHORE is None or _GLOBAL_SEMAPHORE_LOOP is not current_loop:
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(GLOBAL_MAX_WORKERS)
        _GLOBAL_SEMAPHORE_LOOP = current_loop
    return _GLOBAL_SEMAPHORE


# Voice list in-memory TTL cache (prevents redundant Microsoft API calls)
VOICE_CACHE_TTL_SECONDS = 3600.0  # 1 hour
_voices_cache: list[dict[str, Any]] | None = None
_voices_cache_timestamp: float = 0.0
_voices_cache_lock: asyncio.Lock | None = None


def _get_voices_lock() -> asyncio.Lock:
    global _voices_cache_lock
    if _voices_cache_lock is None:
        _voices_cache_lock = asyncio.Lock()
    return _voices_cache_lock


# Mapping from langdetect 2-letter codes to common edge-tts locale prefixes.
LANGUAGE_TO_LOCALE: dict[str, str] = {
    "af": "af-ZA",
    "ar": "ar-SA",
    "bg": "bg-BG",
    "bn": "bn-IN",
    "ca": "ca-ES",
    "cs": "cs-CZ",
    "cy": "cy-GB",
    "da": "da-DK",
    "de": "de-DE",
    "el": "el-GR",
    "en": "en-US",
    "es": "es-ES",
    "et": "et-EE",
    "fa": "fa-IR",
    "fi": "fi-FI",
    "fr": "fr-FR",
    "ga": "ga-IE",
    "gl": "gl-ES",
    "gu": "gu-IN",
    "he": "he-IL",
    "hi": "hi-IN",
    "hr": "hr-HR",
    "hu": "hu-HU",
    "id": "id-ID",
    "it": "it-IT",
    "ja": "ja-JP",
    "jv": "jv-ID",
    "ka": "ka-GE",
    "kk": "kk-KZ",
    "km": "km-KH",
    "kn": "kn-IN",
    "ko": "ko-KR",
    "lo": "lo-LA",
    "lt": "lt-LT",
    "lv": "lv-LV",
    "mk": "mk-MK",
    "ml": "ml-IN",
    "mn": "mn-MN",
    "mr": "mr-IN",
    "ms": "ms-MY",
    "my": "my-MM",
    "nb": "nb-NO",
    "ne": "ne-NP",
    "nl": "nl-NL",
    "pl": "pl-PL",
    "pt": "pt-BR",
    "ro": "ro-RO",
    "ru": "ru-RU",
    "si": "si-LK",
    "sk": "sk-SK",
    "sl": "sl-SI",
    "so": "so-SO",
    "sq": "sq-AL",
    "sr": "sr-RS",
    "su": "su-ID",
    "sv": "sv-SE",
    "sw": "sw-KE",
    "ta": "ta-IN",
    "te": "te-IN",
    "th": "th-TH",
    "tr": "tr-TR",
    "uk": "uk-UA",
    "ur": "ur-PK",
    "uz": "uz-UZ",
    "vi": "vi-VN",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
    "zu": "zu-ZA",
}


# ---------------------------------------------------------------------------
# Utilities & Validation
# ---------------------------------------------------------------------------

def is_valid_chunk(filepath: str) -> bool:
    """Check that an MP3 file exists and is not empty/corrupted (>= 1 KB)."""
    try:
        return os.path.isfile(filepath) and os.path.getsize(filepath) >= MIN_FILE_SIZE
    except OSError:
        return False


async def async_safe_remove(filepath: str) -> None:
    """Non-blocking file removal with async retry for transient OS file locks."""
    for _ in range(3):
        try:
            if os.path.lexists(filepath):
                await asyncio.to_thread(os.remove, filepath)
            return
        except PermissionError:
            await asyncio.sleep(0.02)
        except OSError:
            return


def safe_remove(filepath: str) -> None:
    """Safely remove a file synchronously, tolerating transient locks (for test compat)."""
    for _ in range(3):
        try:
            if os.path.lexists(filepath):
                os.remove(filepath)
            return
        except PermissionError:
            time.sleep(0.02)
        except OSError:
            return


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Detect the language of *text* and return the best-matching edge-tts locale
    code (e.g. 'en-US'). Samples the first 1,000 characters to prevent high CPU overhead.

    Raises ValueError if detection fails.
    """
    stripped = text.strip() if text else ""
    if not stripped:
        raise ValueError("Could not detect language: text is empty")

    # Slice up to LANG_DETECT_SAMPLE_CHARS at a whitespace boundary to avoid scanning 46 KB
    sample = stripped[:LANG_DETECT_SAMPLE_CHARS]
    if len(stripped) > LANG_DETECT_SAMPLE_CHARS:
        last_space = sample.rfind(" ")
        if last_space > LANG_DETECT_SAMPLE_CHARS // 2:
            sample = sample[:last_space]

    try:
        lang_code = detect(sample).lower()
    except LangDetectException as exc:
        raise ValueError(f"Could not detect language: {exc}") from exc

    if lang_code in LANGUAGE_TO_LOCALE:
        return LANGUAGE_TO_LOCALE[lang_code]

    for key, locale in LANGUAGE_TO_LOCALE.items():
        if key.startswith(lang_code):
            return locale

    raise ValueError(
        f"Detected language '{lang_code}' is not supported by edge-tts"
    )


# ---------------------------------------------------------------------------
# Voice listing
# ---------------------------------------------------------------------------

async def _fetch_all_voices_cached() -> list[dict[str, Any]]:
    """Return cached edge-tts voice list, refreshing only when TTL expires."""
    global _voices_cache, _voices_cache_timestamp
    now = time.monotonic()

    if _voices_cache is not None and (now - _voices_cache_timestamp) < VOICE_CACHE_TTL_SECONDS:
        return _voices_cache

    async with _get_voices_lock():
        now = time.monotonic()
        if _voices_cache is not None and (now - _voices_cache_timestamp) < VOICE_CACHE_TTL_SECONDS:
            return _voices_cache

        all_voices = await edge_tts.list_voices()
        _voices_cache = all_voices
        _voices_cache_timestamp = time.monotonic()
        logger.info("Refreshed edge-tts voice cache (%d voices)", len(all_voices))
        return _voices_cache


async def get_voices_for_language(language: str) -> list[dict]:
    """
    Return available edge-tts voices for a given language code using cached voice list.
    """
    all_voices = await _fetch_all_voices_cached()

    lang_lower = language.lower()
    prefix = f"{lang_lower}-" if len(lang_lower) == 2 else lang_lower

    matched: list[dict] = []
    for voice in all_voices:
        short = voice.get("ShortName", "")
        if short.lower().startswith(prefix):
            matched.append(
                {
                    "short_name": voice["ShortName"],
                    "gender": voice.get("Gender", "Unknown"),
                    "locale": voice.get("Locale", ""),
                }
            )

    return matched


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def split_text_into_chunks(
    text: str, max_words: int = MAX_WORDS_PER_CHUNK
) -> list[str]:
    """
    Split *text* into chunks of ~max_words, preserving structure without cutting mid-sentence.

    Universal split hierarchy:
      1. Paragraph breaks (double newlines)
      2. Sentence endings (.!?...) avoiding abbreviation lookbehinds
      3. Clause boundaries (; , — –) for oversized sentences
      4. Word boundaries (last resort)
    """
    if not text or not text.strip():
        return []

    def wc(s: str) -> int:
        return len(s.split())

    def split_sentences(paragraph: str) -> list[str]:
        p = paragraph.replace("...", "\u2026")
        parts = _SENTENCE_SPLIT_RE.split(p)
        return [s.strip() for s in parts if s.strip()]

    def split_oversized(sentence: str, limit: int) -> list[str]:
        clauses = _CLAUSE_SPLIT_RE.split(sentence)
        if len(clauses) > 1:
            parts, buf, n = [], [], 0
            for cl in clauses:
                cw = wc(cl)
                if n + cw > limit and buf:
                    parts.append(" ".join(buf))
                    buf, n = [cl], cw
                else:
                    buf.append(cl)
                    n += cw
            if buf:
                parts.append(" ".join(buf))
            return parts
        words = sentence.split()
        return [" ".join(words[i : i + limit]) for i in range(0, len(words), limit)]

    paragraphs = _PARAGRAPH_SPLIT_RE.split(text.replace("\r\n", "\n"))
    sentences: list[str] = []
    for para in paragraphs:
        para_clean = para.strip()
        if para_clean:
            sentences.extend(split_sentences(para_clean))

    chunks: list[str] = []
    chunk: list[str] = []
    count = 0

    for sent in sentences:
        sw = wc(sent)
        if sw > max_words:
            if chunk:
                chunks.append(" ".join(chunk))
                chunk, count = [], 0
            chunks.extend(split_oversized(sent, max_words))
            continue
        if count + sw > max_words:
            if chunk:
                chunks.append(" ".join(chunk))
            chunk, count = [sent], sw
        else:
            chunk.append(sent)
            count += sw

    if chunk:
        chunks.append(" ".join(chunk))

    logger.info("Split text into %d chunk(s)", len(chunks))
    return chunks


# ---------------------------------------------------------------------------
# TTS generation (Native Async with Dual Concurrency Control)
# ---------------------------------------------------------------------------

async def _generate_chunk(
    index: int,
    text: str,
    voice: str,
    output_dir: str,
    total_chunks: int,
    semaphore: asyncio.Semaphore | None = None,
    request_semaphore: asyncio.Semaphore | None = None,
    global_semaphore: asyncio.Semaphore | None = None,
    on_chunk_done: Callable[[], None] | None = None,
) -> str:
    """Generate a single chunk MP3 using atomic writes, jittered backoff, and release during sleep."""
    final_path = os.path.join(output_dir, f"chunk_{index:04d}.mp3")
    tmp_path = os.path.join(output_dir, f"chunk_{index:04d}.mp3.tmp")
    last_error: Exception | None = None

    req_sem = request_semaphore or semaphore or asyncio.Semaphore(1)
    glob_sem = global_semaphore or _get_global_semaphore()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Acquire semaphores ONLY during active network synthesis.
            # Releasing before backoff sleep prevents starving healthy chunks.
            async with req_sem, glob_sem:
                logger.info(
                    "Generating chunk %d/%d (Attempt %d/%d) …",
                    index + 1,
                    total_chunks,
                    attempt,
                    MAX_RETRIES,
                )

                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(tmp_path)

                valid = await asyncio.to_thread(is_valid_chunk, tmp_path)
                if valid:
                    await asyncio.to_thread(os.replace, tmp_path, final_path)
                    logger.info("Chunk %d/%d saved: %s", index + 1, total_chunks, final_path)
                    if on_chunk_done:
                        on_chunk_done()
                    return final_path

                size = (
                    await asyncio.to_thread(os.path.getsize, tmp_path)
                    if await asyncio.to_thread(os.path.isfile, tmp_path)
                    else 0
                )
                raise RuntimeError(f"Output file too small ({size} bytes)")

        except asyncio.CancelledError:
            await async_safe_remove(tmp_path)
            raise

        except Exception as exc:
            last_error = exc
            await async_safe_remove(tmp_path)
            if attempt < MAX_RETRIES:
                backoff = (2 ** attempt) + random.uniform(0.15, 1.5)
                logger.warning(
                    "Error generating chunk %d/%d: %s. Retrying in %.2fs…",
                    index + 1,
                    total_chunks,
                    str(exc),
                    backoff,
                )
                # Sleep OUTSIDE semaphore contexts so other tasks can proceed
                await asyncio.sleep(backoff)

    logger.error(
        "Failed to generate chunk %d/%d after %d attempts: %s",
        index + 1,
        total_chunks,
        MAX_RETRIES,
        last_error,
    )
    raise RuntimeError(
        f"Chunk {index + 1} failed after {MAX_RETRIES} attempts: {last_error}"
    )


async def process_text_to_speech(
    text: str,
    voice: str,
    temp_dir: str,
    on_progress: Callable[[int, str], Any] | None = None,
) -> list[str]:
    """
    Full TTS pipeline:
      1. Split *text* into chunks asynchronously.
      2. Generate audio concurrently with per-request and global throttling.
      3. Cancel all sibling tasks immediately if any chunk fails permanently or pipeline is aborted.
      4. Report real-time progress via *on_progress(percent, status)*.
      5. Return ordered list of chunk file paths.
    """
    chunks = await asyncio.to_thread(split_text_into_chunks, text)
    if not chunks:
        raise ValueError("No processable text after splitting")

    total = len(chunks)
    if on_progress:
        on_progress(10, f"Split text into {total} chunk(s)")

    completed = 0
    workers = min(PER_REQUEST_MAX_WORKERS, total)
    request_semaphore = asyncio.Semaphore(workers)
    global_semaphore = _get_global_semaphore()

    def on_chunk_done() -> None:
        nonlocal completed
        completed += 1
        if on_progress:
            pct = 10 + int((completed / total) * 80)
            on_progress(pct, f"Generating audio ({completed}/{total} chunks)")

    tasks = [
        asyncio.create_task(
            _generate_chunk(
                index=i,
                text=chunks[i],
                voice=voice,
                output_dir=temp_dir,
                total_chunks=total,
                request_semaphore=request_semaphore,
                global_semaphore=global_semaphore,
                on_chunk_done=on_chunk_done,
            )
        )
        for i in range(total)
    ]

    try:
        paths = await asyncio.gather(*tasks)
    except BaseException:
        # Cancel ALL sibling tasks on CancelledError OR any chunk failure (BaseException)
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    return list(paths)
