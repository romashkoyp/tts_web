"""
TTS Service — text chunking, edge-tts orchestration, language detection, voice listing.

Adapted from the prototype script text_to_speech_edge.py.
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
MAX_WORDS_PER_CHUNK = WORDS_PER_MINUTE * 4  # ~600 words per chunk

# Reduced concurrency: Microsoft's servers are sensitive to too many 
# simultaneous connections (often resulting in 503 errors).
MAX_WORKERS = 20
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # seconds

# Mapping from langdetect 2-letter codes to common edge-tts locale prefixes.
# edge-tts uses locale codes like "en-US", "ru-RU", "fi-FI", etc.
# When the detected language doesn't have an exact match, we fall back to
# the most common regional variant.
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
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Detect the language of *text* and return the best-matching edge-tts locale
    code (e.g. "en-US").

    Raises ValueError if detection fails.
    """
    try:
        # langdetect returns ISO-639-1 codes like "en", "ru", "fi", etc.
        lang_code = detect(text).lower()
    except LangDetectException as exc:
        raise ValueError(f"Could not detect language: {exc}") from exc

    # Direct mapping
    if lang_code in LANGUAGE_TO_LOCALE:
        return LANGUAGE_TO_LOCALE[lang_code]

    # Try prefix match (e.g. "zh-cn" → "zh-CN")
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

    *language* can be either:
      - a 2-letter code like "en" (we expand to "en-" prefix match), or
      - a full locale like "en-US" (exact prefix match).

    Returns a list of dicts:
        [{ "short_name": "en-US-GuyNeural", "gender": "Male", "locale": "en-US" }, ...]
    """
    all_voices = await edge_tts.list_voices()

    # Normalise the search prefix
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
    Split *text* into chunks of at most *max_words* words, preserving
    sentence boundaries where possible.
    """
    if not text or not text.strip():
        return []

    # Split on sentence-ending punctuation followed by whitespace
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_word_count = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())

        if current_word_count + sentence_words > max_words and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_word_count = sentence_words
        else:
            current_chunk.append(sentence)
            current_word_count += sentence_words

    if current_chunk:
        chunks.append(" ".join(current_chunk))

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
    """Generate a single chunk MP3 with exponential backoff retries."""
    output_path = os.path.join(output_dir, f"chunk_{index:04d}.mp3")
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.info("Generating chunk %d/%d (Attempt %d/%d) …", 
                        index + 1, total_chunks, attempt + 1, MAX_RETRIES)
            
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            
            logger.info("Chunk %d/%d saved: %s", index + 1, total_chunks, output_path)
            return output_path
            
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(
                    "Error generating chunk %d/%d: %s. Retrying in %ds…",
                    index + 1, total_chunks, str(exc), wait_time
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error("Failed to generate chunk %d/%d after %d attempts.", 
                             index + 1, total_chunks, MAX_RETRIES)
                raise exc

    return output_path


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


async def process_text_to_speech(
    text: str,
    voice: str,
    temp_dir: str,
) -> list[str]:
    """
    Full TTS pipeline:
      1. Split *text* into chunks.
      2. Generate audio for each chunk concurrently using a thread pool.
      3. Return ordered list of chunk file paths.

    *voice* is an edge-tts ShortName like "en-US-GuyNeural".
    *temp_dir* is a writable directory for intermediate chunk files.
    """
    chunks = split_text_into_chunks(text)
    if not chunks:
        raise ValueError("No processable text after splitting")

    total = len(chunks)
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            loop.run_in_executor(
                executor,
                _run_chunk_sync,
                i,
                chunk,
                voice,
                temp_dir,
                total,
            )
            for i, chunk in enumerate(chunks)
        ]
        paths = await asyncio.gather(*futures)

    # Return in correct order (enumerate already provides ordering)
    return list(paths)
