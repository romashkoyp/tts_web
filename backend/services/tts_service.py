"""
TTS Service — text chunking, edge-tts orchestration, language detection, voice listing.

Adapted from audiobook.py.
"""

import re
import asyncio
import os
import logging
from concurrent.futures import ThreadPoolExecutor

import edge_tts
from langdetect import detect, LangDetectException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WORDS_PER_MINUTE = 150
MAX_WORDS_PER_CHUNK = WORDS_PER_MINUTE * 8  # ~1200 words per chunk
MIN_FILE_SIZE = 1024  # bytes — valid MP3 is at least ~1 KB

MAX_WORKERS = 20
MAX_RETRIES = 3

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
    return os.path.isfile(filepath) and os.path.getsize(filepath) >= MIN_FILE_SIZE


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Detect the language of *text* and return the best-matching edge-tts locale
    code (e.g. "en-US").

    Raises ValueError if detection fails.
    """
    try:
        lang_code = detect(text).lower()
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

async def get_voices_for_language(language: str) -> list[dict]:
    """
    Return available edge-tts voices for a given language code.
    """
    all_voices = await edge_tts.list_voices()

    lang_lower = language.lower()
    if len(lang_lower) == 2:
        prefix = f"{lang_lower}-"
    else:
        prefix = lang_lower

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
      2. Sentence endings (.!?...) followed by uppercase / quote / dash / bracket
      3. Clause boundaries (; , — –) for oversized sentences
      4. Word boundaries (last resort)
    """
    if not text or not text.strip():
        return []

    def wc(s: str) -> int:
        return len(s.split())

    def split_sentences(paragraph: str) -> list[str]:
        p = paragraph.replace("...", "\u2026")
        parts = re.split(r"(?<=[.!?\u2026])\s+(?=[^\s\da-z])", p)
        return [s.strip() for s in parts if s.strip()]

    def split_oversized(sentence: str, limit: int) -> list[str]:
        clauses = re.split(r"(?<=[;,])\s+|\s+(?=[—–]\s)", sentence)
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

    paragraphs = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    sentences: list[str] = []
    for para in paragraphs:
        para_clean = " ".join(para.split())
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
# TTS generation
# ---------------------------------------------------------------------------

async def _generate_chunk(
    index: int,
    text: str,
    voice: str,
    output_dir: str,
    total_chunks: int,
) -> str:
    """Generate a single chunk MP3 with retry and validation."""
    output_path = os.path.join(output_dir, f"chunk_{index:04d}.mp3")
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Generating chunk %d/%d (Attempt %d/%d) …",
                index + 1,
                total_chunks,
                attempt,
                MAX_RETRIES,
            )

            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)

            if is_valid_chunk(output_path):
                logger.info("Chunk %d/%d saved: %s", index + 1, total_chunks, output_path)
                return output_path

            size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
            raise RuntimeError(f"Output file too small ({size} bytes)")

        except Exception as exc:
            last_error = exc
            if os.path.isfile(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            if attempt < MAX_RETRIES:
                wait_time = 2**attempt
                logger.warning(
                    "Error generating chunk %d/%d: %s. Retrying in %ds…",
                    index + 1,
                    total_chunks,
                    str(exc),
                    wait_time,
                )
                await asyncio.sleep(wait_time)

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


def _run_chunk_sync(
    index: int,
    text: str,
    voice: str,
    output_dir: str,
    total_chunks: int,
) -> str:
    """Thread-safe wrapper: creates a fresh event loop per thread."""
    return asyncio.run(
        _generate_chunk(index, text, voice, output_dir, total_chunks)
    )


from typing import Callable, Any

async def process_text_to_speech(
    text: str,
    voice: str,
    temp_dir: str,
    on_progress: Callable[[int, str], Any] | None = None,
) -> list[str]:
    """
    Full TTS pipeline:
      1. Split *text* into chunks.
      2. Generate audio for each chunk concurrently using a thread pool.
      3. Report real-time progress via *on_progress(percent, status)* if provided.
      4. Return ordered list of chunk file paths.
    """
    chunks = split_text_into_chunks(text)
    if not chunks:
        raise ValueError("No processable text after splitting")

    total = len(chunks)
    if on_progress:
        on_progress(10, f"Split text into {total} chunk(s)")

    completed = 0
    loop = asyncio.get_running_loop()

    def _done_callback(fut: asyncio.Future) -> None:
        nonlocal completed
        completed += 1
        if on_progress:
            pct = 10 + int((completed / total) * 80)
            on_progress(pct, f"Generating audio ({completed}/{total} chunks)")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for i in range(total):
            fut = loop.run_in_executor(
                executor,
                _run_chunk_sync,
                i,
                chunks[i],
                voice,
                temp_dir,
                total,
            )
            if on_progress:
                fut.add_done_callback(_done_callback)
            futures.append(fut)

        paths = await asyncio.gather(*futures)

    return list(paths)


