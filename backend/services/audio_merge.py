"""
Audio Merge Service — concatenate chunk MP3 files into a single output using pydub.

Adapted from the prototype script chunks_to_single_file.py.
"""

import io
import logging

from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Output bitrate for the merged MP3
OUTPUT_BITRATE = "48k"


def merge_audio_chunks(chunk_paths: list[str]) -> io.BytesIO:
    """
    Load each MP3 from *chunk_paths* (in order), concatenate them, and export
    the result to an in-memory BytesIO buffer at 48 kbps.

    Returns the BytesIO buffer seeked to position 0, ready for streaming.

    Raises:
        ValueError: if *chunk_paths* is empty.
        Exception: if any chunk file cannot be loaded or the merge fails.
    """
    if not chunk_paths:
        raise ValueError("No chunk files to merge")

    logger.info("Merging %d chunk(s) …", len(chunk_paths))

    combined = AudioSegment.empty()
    for i, path in enumerate(chunk_paths):
        logger.info("Loading chunk %d/%d: %s", i + 1, len(chunk_paths), path)
        segment = AudioSegment.from_mp3(path)
        combined += segment

    buffer = io.BytesIO()
    combined.export(buffer, format="mp3", bitrate=OUTPUT_BITRATE)
    buffer.seek(0)

    logger.info(
        "Merge complete — output size: %.1f KB",
        buffer.getbuffer().nbytes / 1024,
    )
    return buffer
