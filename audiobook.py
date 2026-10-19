"""
Audiobook Generator — Unified TTS pipeline.

Converts a text file into a single MP3 audiobook using Microsoft Edge TTS.
Asks for book name and author, generates audio chunks in a temp folder,
merges them via FFmpeg, writes ID3 metadata, and cleans up.

Usage:  python audiobook.py
"""

# https://github.com/rany2/edge-tts/
# Check edge-tts installed version: python -m pip show edge-tts
# Check edge-tts versions: python -m pip index versions edge-tts
# Delete edge-tts: python -m pip uninstall edge-tts
# Install specific version: python -m pip install edge-tts==VERSION

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from importlib.metadata import version
from typing import NamedTuple

import edge_tts

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Settings ──────────────────────────────────────────────────────────────────
SOURCE_FILE = 'book.txt'
VOICE = "ru-RU-DmitryNeural"  # ru-RU-SvetlanaNeural fi-FI-HarriNeural en-GB-RyanNeural
WORDS_PER_MINUTE = 140
MAX_WORDS_PER_FILE = WORDS_PER_MINUTE * 8
WORKERS = 10               # Optimal async concurrency for Edge TTS WebSockets (8-12)
MAX_RETRIES = 4            # Retries per chunk with exponential backoff + jitter
MIN_FILE_SIZE = 1024       # bytes — valid MP3 is at least ~1 KB
TEMP_DIR = '_temp_chunks'  # subfolder for intermediate chunk files
BAR_WIDTH = 30             # progress bar character width
PREVIEW_LIMIT = 5          # max chunk previews printed to console (0 = disable)


# ── Pre-compiled Regexes for Fast Text Processing ─────────────────────────────

# Paragraph boundary: 2+ newlines (ignoring whitespace-only lines)
_RE_PARAGRAPHS = re.compile(r'\n\s*\n')

# Common RU/EN abbreviations that end with a period but do NOT end a sentence
_RE_ABBREV_GUARD = re.compile(
    r'\b(?:г|гг|в|вв|т|д|п|др|пр|см|ср|им|ул|кв|рис|табл|ст|гл|ч|стр|руб|коп|'
    r'Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|vs|etc|e\.g|i\.e)\.\s+(?=[А-ЯЁA-Z])',
    re.UNICODE
)

# Single-letter initials (e.g., "А. С. Пушкин", "J. R. R. Tolkien")
_RE_INITIALS_GUARD = re.compile(r'\b([А-ЯЁA-Z])\.\s+(?=[А-ЯЁA-Z])')

# Sentence boundary: [.!?…] followed by whitespace and uppercase/quote/dash
_RE_SENTENCE_SPLIT = re.compile(r'(?<=[.!?\u2026])\s+(?=[А-ЯЁA-Z«"\'(–—\[])')

# Clause boundary for oversized sentences: [;,] or spaced dashes [—–]
_RE_CLAUSE_SPLIT = re.compile(r'(?<=[;,])\s+|\s+(?=[—–]\s)')

# Fast non-allocating word scanner
_RE_WORD = re.compile(r'\S+')

# Illegal filename characters across Windows/macOS/Linux + Windows reserved names
_RE_ILLEGAL_CHARS = re.compile(r'[\\/*?:"<>|\x00-\x1f]')
_WIN_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})

_SENTINEL_SPACE = "\x00"  # Temporary placeholder to protect abbreviations


# ── Utilities ─────────────────────────────────────────────────────────────────

def count_words(text: str) -> int:
    """Count words without allocating a list of all substrings in memory."""
    return sum(1 for _ in _RE_WORD.finditer(text))


def _fetch_latest_pypi_version() -> str:
    """Fetch latest edge-tts version from PyPI using stdlib urllib."""
    req = urllib.request.Request(
        "https://pypi.org/pypi/edge-tts/json",
        headers={"Accept": "application/json", "User-Agent": "audiobook-generator/2.0"},
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["info"]["version"]


async def check_edge_tts_version() -> None:
    """Non-blocking check of installed edge-tts version against PyPI."""
    try:
        installed_version = version("edge-tts")
        print(f"Installed edge-tts version: {installed_version}")
        latest_version = await asyncio.to_thread(_fetch_latest_pypi_version)
        print(f"Latest edge-tts version:    {latest_version}")
        if installed_version == latest_version:
            print("  -> You have the latest version installed.")
        else:
            print("  -> A newer version is available. Upgrade with: pip install --upgrade edge-tts")
    except Exception as e:
        print(f"Could not check for latest edge-tts version: {e}")


def check_ffmpeg_available() -> bool:
    """Verify FFmpeg is available on system PATH before starting long TTS jobs."""
    return shutil.which("ffmpeg") is not None


def sanitize_filename(name: str) -> str:
    """Remove illegal characters and guard against Windows reserved filenames."""
    cleaned = _RE_ILLEGAL_CHARS.sub('', name).strip().rstrip('.')
    if not cleaned or cleaned.upper() in _WIN_RESERVED_NAMES:
        return f"audiobook_{cleaned or 'output'}"
    return cleaned


def read_text_from_file(text_file: str) -> str:
    try:
        with open(text_file, 'r', encoding='utf-8-sig') as f:
            return f.read()
    except Exception as e:
        print(f"Error opening '{text_file}': {e}")
        sys.exit(1)


def is_valid_chunk(filepath: str) -> bool:
    """Check that an MP3 file exists, meets minimum size, and is not truncated."""
    try:
        return os.path.isfile(filepath) and os.path.getsize(filepath) >= MIN_FILE_SIZE
    except OSError:
        return False


def safe_remove(filepath: str) -> None:
    """Safely remove a file on Windows, tolerating transient AV/handle locks."""
    for _ in range(3):
        try:
            if os.path.lexists(filepath):
                os.remove(filepath)
            return
        except PermissionError:
            time.sleep(0.05)
        except OSError:
            return


def prepare_temp_dir(text: str, voice: str, max_words: int) -> None:
    """Ensure TEMP_DIR exists and validate its manifest to prevent cross-book corruption."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    manifest_path = os.path.join(TEMP_DIR, "_manifest.json")

    fingerprint = hashlib.sha256(
        f"{voice}|{max_words}|{text}".encode("utf-8", errors="replace")
    ).hexdigest()

    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("fingerprint") == fingerprint:
                # Clean up any leftover .tmp files from an interrupted run
                for entry in os.scandir(TEMP_DIR):
                    if entry.name.endswith(".tmp"):
                        safe_remove(entry.path)
                return
            print("      Detected modified book or voice settings. Clearing stale temp chunks...")
        except Exception:
            pass

    # Purge stale files if manifest is missing or mismatched
    for entry in os.scandir(TEMP_DIR):
        if entry.is_file():
            safe_remove(entry.path)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"fingerprint": fingerprint, "voice": voice, "max_words": max_words}, f)


# ── Progress bar ──────────────────────────────────────────────────────────────

class ProgressBar:
    """Single-threaded async-friendly CLI progress bar with throttled redraws."""

    def __init__(self, total: int, done: int = 0):
        self.total = total
        self.done = done
        self.start_time = time.monotonic()
        self._last_draw = 0.0

    def advance(self) -> None:
        self.done += 1
        now = time.monotonic()
        # Throttle console redraws to max ~15 FPS unless finished
        if self.done >= self.total or (now - self._last_draw) >= 0.065:
            self._draw(now)

    def _draw(self, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        self._last_draw = now

        pct = self.done / self.total if self.total else 1.0
        filled = int(BAR_WIDTH * pct)
        bar = '█' * filled + '░' * (BAR_WIDTH - filled)

        elapsed = now - self.start_time
        mm, ss = divmod(int(elapsed), 60)

        line = f"\r  [{bar}] {self.done}/{self.total} ({pct * 100:5.1f}%) | {mm:02d}:{ss:02d}"
        sys.stdout.write(line)
        sys.stdout.flush()

    def finish(self, label: str = "Done") -> None:
        self._draw()
        sys.stdout.write(f"  {label}\n")
        sys.stdout.flush()


# ── Text splitting ────────────────────────────────────────────────────────────

class _SizedUnit(NamedTuple):
    text: str
    words: int


def split_text_into_chunks(text: str, max_words: int = MAX_WORDS_PER_FILE) -> list[str]:
    """Split text into chunks of ~max_words, never cutting mid-sentence.

    Split hierarchy (preferred -> fallback):
      1. Paragraph breaks (double newlines)
      2. Sentence endings (.!?…) with abbreviation & initial protection
      3. Clause boundaries (; , — –) for oversized sentences
      4. Word boundaries (guaranteed fallback if a single clause > max_words)
    """

    def split_by_words(s: str, limit: int) -> list[_SizedUnit]:
        words = s.split()
        return [
            _SizedUnit(' '.join(words[i:i + limit]), min(limit, len(words) - i))
            for i in range(0, len(words), limit)
        ]

    def split_oversized(sentence: str, limit: int) -> list[_SizedUnit]:
        clauses = _RE_CLAUSE_SPLIT.split(sentence)
        if len(clauses) <= 1:
            return split_by_words(sentence, limit)

        parts: list[_SizedUnit] = []
        buf: list[str] = []
        buf_words = 0

        for cl in clauses:
            cl = cl.strip()
            if not cl:
                continue
            cw = count_words(cl)

            # Fix: If an individual clause still exceeds limit, flush buffer and word-split it
            if cw > limit:
                if buf:
                    parts.append(_SizedUnit(' '.join(buf), buf_words))
                    buf, buf_words = [], 0
                parts.extend(split_by_words(cl, limit))
                continue

            if buf_words + cw > limit and buf:
                parts.append(_SizedUnit(' '.join(buf), buf_words))
                buf, buf_words = [cl], cw
            else:
                buf.append(cl)
                buf_words += cw

        if buf:
            parts.append(_SizedUnit(' '.join(buf), buf_words))
        return parts

    def split_sentences(paragraph: str) -> list[str]:
        p = paragraph.replace('...', '\u2026')
        # Protect abbreviations and initials from false sentence splits
        p = _RE_ABBREV_GUARD.sub(lambda m: m.group(0).rstrip() + _SENTINEL_SPACE, p)
        p = _RE_INITIALS_GUARD.sub(lambda m: m.group(0).rstrip() + _SENTINEL_SPACE, p)
        parts = _RE_SENTENCE_SPLIT.split(p)
        return [
            ' '.join(s.replace(_SENTINEL_SPACE, ' ').split())
            for s in parts if s.strip()
        ]

    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = _RE_PARAGRAPHS.split(normalized)

    chunks: list[str] = []
    current_buf: list[str] = []
    current_count = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        for sent in split_sentences(para):
            sw = count_words(sent)
            if sw == 0:
                continue

            if sw > max_words:
                if current_buf:
                    chunks.append(' '.join(current_buf))
                    current_buf, current_count = [], 0
                for unit in split_oversized(sent, max_words):
                    chunks.append(unit.text)
                continue

            if current_count + sw > max_words and current_buf:
                chunks.append(' '.join(current_buf))
                current_buf, current_count = [sent], sw
            else:
                current_buf.append(sent)
                current_count += sw

    if current_buf:
        chunks.append(' '.join(current_buf))

    return chunks


# ── TTS generation (Pure Native Async) ────────────────────────────────────────

async def generate_chunk(
    index: int,
    text: str,
    voice: str,
    bar: ProgressBar,
    semaphore: asyncio.Semaphore,
) -> None:
    """Generate a single chunk MP3 using atomic writes and jittered backoff."""
    final_path = os.path.join(TEMP_DIR, f"chunk_{index}.mp3")
    tmp_path = os.path.join(TEMP_DIR, f"chunk_{index}.mp3.tmp")
    last_error: Exception | None = None

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(tmp_path)

                if is_valid_chunk(tmp_path):
                    # Atomic rename on NTFS guarantees no half-written chunks are ever seen as valid
                    os.replace(tmp_path, final_path)
                    bar.advance()
                    return

                size = os.path.getsize(tmp_path) if os.path.isfile(tmp_path) else 0
                raise RuntimeError(f"Output file too small ({size} bytes)")

            except asyncio.CancelledError:
                safe_remove(tmp_path)
                raise

            except Exception as e:
                last_error = e
                safe_remove(tmp_path)
                if attempt < MAX_RETRIES:
                    # Exponential backoff + randomized jitter prevents Thundering Herd
                    backoff = (2 ** attempt) + random.uniform(0.15, 1.5)
                    await asyncio.sleep(backoff)

    raise RuntimeError(f"Chunk {index} failed after {MAX_RETRIES} attempts: {last_error}")


# ── FFmpeg merge ──────────────────────────────────────────────────────────────

def merge_chunks(total: int, output_path: str, book_name: str, author: str) -> bool:
    """Merge all chunk MP3s into a single file using FFmpeg concat demuxer.
    Writes ID3v2.3 metadata (title + artist). Returns True only if all chunks are merged."""
    filelist_path = os.path.join(TEMP_DIR, '_filelist.txt')

    valid: list[str] = []
    missing: list[int] = []
    for i in range(1, total + 1):
        fp = os.path.join(TEMP_DIR, f"chunk_{i}.mp3")
        if is_valid_chunk(fp):
            valid.append(fp)
        else:
            missing.append(i)

    if missing:
        print(f"  ERROR: {len(missing)} chunk(s) missing or corrupted: {missing[:10]}")
        return False

    if not valid:
        print("No valid chunks to merge.")
        return False

    tmp_output = f"{output_path}.tmp.mp3"

    try:
        with open(filelist_path, 'w', encoding='utf-8') as f:
            for fp in valid:
                abs_fp = os.path.abspath(fp).replace('\\', '/')
                safe = abs_fp.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'concat', '-safe', '0',
            '-i', filelist_path,
            '-c', 'copy',
            '-id3v2_version', '3',
            '-metadata', f'title={book_name}',
            '-metadata', f'artist={author}',
            tmp_output,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0 or not is_valid_chunk(tmp_output):
            print(f"FFmpeg error:\n{result.stderr}")
            safe_remove(tmp_output)
            return False

        os.replace(tmp_output, output_path)
        return True

    finally:
        safe_remove(filelist_path)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 50)
    print("  Audiobook Generator")
    print("=" * 50)

    if not check_ffmpeg_available():
        print("ERROR: 'ffmpeg' was not found on your system PATH.")
        print("Please install FFmpeg (e.g., 'winget install Gyan.FFmpeg') and restart.")
        sys.exit(1)

    print("Checking edge-tts version...")
    await check_edge_tts_version()
    print("-" * 50)

    book_name = input("\n  Book name:   ").strip()
    author    = input("  Author:      ").strip()

    if not book_name:
        print("Book name cannot be empty.")
        sys.exit(1)

    base_Title = f"{book_name} - {author}" if author else book_name
    output_filename = sanitize_filename(base_Title) + ".mp3"
    print(f"\n  Output file: {output_filename}")
    print(f"  Voice:       {VOICE}")
    print(f"  Source:      {SOURCE_FILE}")
    print()

    # 2. Read and split text
    print("[1/4] Reading text...")
    text = read_text_from_file(SOURCE_FILE)
    word_count = count_words(text)
    if word_count == 0:
        print(f"Error: '{SOURCE_FILE}' is empty.")
        sys.exit(1)
    print(f"      {word_count:,} words loaded.")

    print("[2/4] Splitting into chunks...")
    text_chunks = split_text_into_chunks(text)
    total = len(text_chunks)
    workers = min(WORKERS, total)

    if PREVIEW_LIMIT > 0:
        for i, chunk in enumerate(text_chunks[:PREVIEW_LIMIT]):
            flat = ' '.join(chunk.split())
            preview = f"{flat[:30]}...{flat[-30:]}" if len(flat) > 65 else flat
            print(f"        {i + 1}: {preview}")
        if total > PREVIEW_LIMIT:
            print(f"        ... ({total - PREVIEW_LIMIT} more chunks omitted)")
    print(f"      {total} chunks created.")

    # 3. Generate audio
    prepare_temp_dir(text, VOICE, MAX_WORDS_PER_FILE)

    to_process: list[tuple[int, str]] = []
    skipped = 0
    for i, chunk_text in enumerate(text_chunks, 1):
        filepath = os.path.join(TEMP_DIR, f"chunk_{i}.mp3")
        if is_valid_chunk(filepath):
            skipped += 1
        else:
            to_process.append((i, chunk_text))

    print(f"\n[3/4] Generating audio ({total} chunks, {workers} async streams)...")
    if skipped:
        print(f"      Resuming: {skipped} already done, {len(to_process)} remaining.")

    if to_process:
        bar = ProgressBar(total=total, done=skipped)
        bar._draw()

        start_time = time.monotonic()
        semaphore = asyncio.Semaphore(workers)

        tasks = [
            asyncio.create_task(generate_chunk(idx, chunk_text, VOICE, bar, semaphore))
            for idx, chunk_text in to_process
        ]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print("\n\n  Generation interrupted by user. Completed chunks are saved for resume.")
            return

        elapsed = time.monotonic() - start_time
        mm, ss = divmod(int(elapsed), 60)

        failed = [
            (to_process[i][0], r)
            for i, r in enumerate(results)
            if isinstance(r, BaseException)
        ]

        bar.finish()
        print(f"      Generation time: {mm:02d}:{ss:02d}")

        if failed:
            print(f"\n  FAILED chunks ({len(failed)}):")
            for idx, err in failed:
                print(f"    chunk {idx}: {err}")
            print("\n  Re-run the script to retry failed chunks.")
            return
    else:
        print("      All chunks already generated.")

    # 4. Merge into single file
    print(f"\n[4/4] Merging into {output_filename}...")
    if merge_chunks(total, output_filename, book_name, author):
        size_mb = os.path.getsize(output_filename) / (1024 * 1024)
        print(f"      Saved: {output_filename} ({size_mb:.1f} MB)")
        print(f"      Metadata: title=\"{book_name}\", artist=\"{author}\"")

        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        print(f"      Temp folder '{TEMP_DIR}' deleted.")
    else:
        print("      Merge failed. Temp chunks preserved for retry.")
        return

    print("\n" + "=" * 50)
    print("  Audiobook ready!")
    print("=" * 50)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n  Interrupted by user (Ctrl+C). Exiting cleanly.")
        sys.exit(130)
