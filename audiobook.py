"""
Audiobook Generator — Unified TTS pipeline.

Converts a text file into a single MP3 audiobook using Microsoft Edge TTS.
Asks for book name and author, generates audio chunks in a temp folder,
merges them via FFmpeg, writes ID3 metadata, and cleans up.

Usage:  python audiobook.py
"""

import re
import os
import sys
import shutil
import asyncio
import time
import threading
import subprocess
import concurrent.futures
from importlib.metadata import version
import requests
import edge_tts

# ── Settings ──────────────────────────────────────────────────────────────────
SOURCE_FILE = 'book.txt'
VOICE = "ru-RU-DmitryNeural"  # ru-RU-SvetlanaNeural fi-FI-HarriNeural en-GB-RyanNeural
WORDS_PER_MINUTE = 150
MAX_WORDS_PER_FILE = WORDS_PER_MINUTE * 8
WORKERS = 20
MAX_RETRIES = 3
MIN_FILE_SIZE = 1024       # bytes — valid MP3 is at least ~1 KB
TEMP_DIR = '_temp_chunks'  # subfolder for intermediate chunk files
BAR_WIDTH = 30             # progress bar character width


# ── Utilities ─────────────────────────────────────────────────────────────────

def check_edge_tts_version() -> None:
    """Check installed edge-tts version against latest PyPI release."""
    try:
        installed_version = version("edge-tts")
        print(f"Installed edge-tts version: {installed_version}")
        response = requests.get("https://pypi.org/pypi/edge-tts/json", timeout=5)
        latest_version = response.json()["info"]["version"]
        print(f"Latest edge-tts version:    {latest_version}")
        if installed_version == latest_version:
            print("  -> You have the latest version installed.")
        else:
            print("  -> A newer version is available. Upgrade with: pip install --upgrade edge-tts")
    except Exception as e:
        print(f"Could not check for latest edge-tts version: {e}")


def sanitize_filename(name: str) -> str:
    """Remove characters that are illegal in Windows/macOS/Linux filenames."""
    return re.sub(r'[\\/*?:"<>|]', '', name).strip()


def read_text_from_file(text_file: str) -> str:
    try:
        with open(text_file, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Error opening '{text_file}': {e}")
        sys.exit(1)


def is_valid_chunk(filepath: str) -> bool:
    """Check that an MP3 file exists and is not empty/corrupted."""
    return os.path.isfile(filepath) and os.path.getsize(filepath) >= MIN_FILE_SIZE


# ── Progress bar ──────────────────────────────────────────────────────────────

class ProgressBar:
    """Thread-safe CLI progress bar with elapsed time."""

    def __init__(self, total: int, done: int = 0):
        self.total = total
        self.done = done
        self.start_time = time.time()
        self._lock = threading.Lock()

    def advance(self) -> None:
        with self._lock:
            self.done += 1
            self._draw()

    def _draw(self) -> None:
        pct = self.done / self.total if self.total else 1
        filled = int(BAR_WIDTH * pct)
        bar = '#' * filled + '-' * (BAR_WIDTH - filled)

        elapsed = time.time() - self.start_time
        mm, ss = divmod(int(elapsed), 60)

        line = f"\r  [{bar}] {self.done}/{self.total} | {mm:02d}:{ss:02d}"
        sys.stdout.write(line)
        sys.stdout.flush()

    def finish(self, label: str = "Done") -> None:
        with self._lock:
            self._draw()
        elapsed = time.time() - self.start_time
        mm, ss = divmod(int(elapsed), 60)
        sys.stdout.write(f"  {label}\n")
        sys.stdout.flush()


# ── Text splitting ────────────────────────────────────────────────────────────

def split_text_into_chunks(text: str, max_words: int = MAX_WORDS_PER_FILE) -> list[str]:
    """Split text into chunks of ~max_words, never cutting mid-sentence.

    Split hierarchy (preferred -> fallback):
      1. Paragraph breaks (double newlines)
      2. Sentence endings (.!?...) followed by uppercase / dialogue dash / quote
      3. Clause boundaries (; , — –) for oversized sentences
      4. Word boundaries (last resort)
    """

    def wc(s: str) -> int:
        return len(s.split())

    def split_sentences(paragraph: str) -> list[str]:
        p = paragraph.replace('...', '\u2026')
        parts = re.split(r'(?<=[.!?\u2026])\s+(?=[А-ЯЁA-Z«"\'(–—\[])', p)
        return [s.strip() for s in parts if s.strip()]

    def split_oversized(sentence: str, limit: int) -> list[str]:
        clauses = re.split(r'(?<=[;,])\s+|\s+(?=[—–]\s)', sentence)
        if len(clauses) > 1:
            parts, buf, n = [], [], 0
            for cl in clauses:
                cw = wc(cl)
                if n + cw > limit and buf:
                    parts.append(' '.join(buf))
                    buf, n = [cl], cw
                else:
                    buf.append(cl)
                    n += cw
            if buf:
                parts.append(' '.join(buf))
            return parts
        words = sentence.split()
        return [' '.join(words[i:i + limit]) for i in range(0, len(words), limit)]

    paragraphs = re.split(r'\n\s*\n', text.replace('\r\n', '\n'))
    sentences = []
    for para in paragraphs:
        para = para.strip()
        if para:
            sentences.extend(split_sentences(para))

    chunks = []
    chunk, count = [], 0
    for sent in sentences:
        sw = wc(sent)
        if sw > max_words:
            if chunk:
                chunks.append(' '.join(chunk))
                chunk, count = [], 0
            chunks.extend(split_oversized(sent, max_words))
            continue
        if count + sw > max_words:
            if chunk:
                chunks.append(' '.join(chunk))
            chunk, count = [sent], sw
        else:
            chunk.append(sent)
            count += sw
    if chunk:
        chunks.append(' '.join(chunk))

    return chunks


# ── TTS generation ────────────────────────────────────────────────────────────

async def generate_chunk(index: int, text: str, voice: str,
                         bar: ProgressBar) -> None:
    """Generate a single chunk MP3 with retry and validation."""
    filepath = os.path.join(TEMP_DIR, f"chunk_{index}.mp3")
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(filepath)

            if is_valid_chunk(filepath):
                bar.advance()
                return

            size = os.path.getsize(filepath) if os.path.isfile(filepath) else 0
            raise RuntimeError(f"Output file too small ({size} bytes)")

        except Exception as e:
            last_error = e
            if os.path.isfile(filepath):
                os.remove(filepath)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    raise RuntimeError(f"Chunk {index} failed after {MAX_RETRIES} attempts: {last_error}")


def run_sync_chunk(index: int, text: str, voice: str,
                   bar: ProgressBar) -> None:
    """Wrapper to run the async TTS in a thread-safe way."""
    asyncio.run(generate_chunk(index, text, voice, bar))


# ── FFmpeg merge ──────────────────────────────────────────────────────────────

def merge_chunks(total: int, output_path: str,
                 book_name: str, author: str) -> bool:
    """Merge all chunk MP3s into a single file using FFmpeg concat demuxer.
    Writes ID3 metadata (title + artist). Returns True on success."""
    filelist_path = os.path.join(TEMP_DIR, '_filelist.txt')

    # Build sorted file list
    valid = []
    for i in range(1, total + 1):
        fp = os.path.join(TEMP_DIR, f"chunk_{i}.mp3")
        if is_valid_chunk(fp):
            valid.append(fp)
        else:
            print(f"  WARNING: chunk_{i}.mp3 missing or invalid, skipping.")

    if not valid:
        print("No valid chunks to merge.")
        return False

    try:
        with open(filelist_path, 'w', encoding='utf-8') as f:
            for fp in valid:
                abs_fp = os.path.abspath(fp).replace('\\', '/')
                safe = abs_fp.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', filelist_path,
            '-c', 'copy',
            '-metadata', f'title={book_name}',
            '-metadata', f'artist={author}',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"FFmpeg error:\n{result.stderr}")
            return False
        return True

    finally:
        if os.path.isfile(filelist_path):
            os.remove(filelist_path)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    # 1. User input
    print("=" * 50)
    print("  Audiobook Generator")
    print("=" * 50)
    print("Checking edge-tts version...")
    check_edge_tts_version()
    print("-" * 50)
    book_name = input("\n  Book name:   ").strip()
    author    = input("  Author:      ").strip()

    if not book_name:
        print("Book name cannot be empty.")
        sys.exit(1)

    output_filename = sanitize_filename(f"{book_name} - {author}") + ".mp3" if author else sanitize_filename(book_name) + ".mp3"
    print(f"\n  Output file: {output_filename}")
    print(f"  Voice:       {VOICE}")
    print(f"  Source:      {SOURCE_FILE}")
    print()

    # 2. Read and split text
    print("[1/4] Reading text...")
    text = read_text_from_file(SOURCE_FILE)
    word_count = len(text.split())
    print(f"      {word_count:,} words loaded.")

    print("[2/4] Splitting into chunks...")
    text_chunks = split_text_into_chunks(text)
    total = len(text_chunks)
    print(f"      {total} chunks created.")

    # 3. Generate audio
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Resume support: detect already-generated valid chunks
    to_process = []
    skipped = 0
    for i, chunk_text in enumerate(text_chunks, 1):
        filepath = os.path.join(TEMP_DIR, f"chunk_{i}.mp3")
        if is_valid_chunk(filepath):
            skipped += 1
        else:
            to_process.append((i, chunk_text))

    print(f"\n[3/4] Generating audio ({total} chunks, {WORKERS} workers)...")
    if skipped:
        print(f"      Resuming: {skipped} already done, {len(to_process)} remaining.")

    if to_process:
        bar = ProgressBar(total=total, done=skipped)
        bar._draw()

        start_time = time.time()

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = [
                loop.run_in_executor(
                    executor, run_sync_chunk,
                    idx, chunk_text, VOICE, bar
                ) for idx, chunk_text in to_process
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)

        elapsed = time.time() - start_time
        mm, ss = divmod(int(elapsed), 60)

        # Check for failures
        failed = [(to_process[i][0], r) for i, r in enumerate(results)
                   if isinstance(r, Exception)]

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

        # Clean up temp folder
        shutil.rmtree(TEMP_DIR)
        print(f"      Temp folder '{TEMP_DIR}' deleted.")
    else:
        print("      Merge failed. Temp chunks preserved for retry.")
        return

    print("\n" + "=" * 50)
    print("  Audiobook ready!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
