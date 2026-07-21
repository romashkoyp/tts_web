"""
Audio Merge Service — concatenate chunk MP3 files into a single output using FFmpeg.

Adapted from audiobook.py.
"""

import io
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def merge_audio_chunks(chunk_paths: list[str]) -> io.BytesIO:
    """
    Merge chunk MP3 files from *chunk_paths* (in order) using FFmpeg's concat demuxer
    with stream copy (-c copy), resulting in lossless, rapid concatenation.

    Returns an in-memory BytesIO buffer containing the merged MP3 data.

    Raises:
        ValueError: if *chunk_paths* is empty.
        RuntimeError: if FFmpeg fails or is not found on the system.
    """
    if not chunk_paths:
        raise ValueError("No chunk files to merge")

    logger.info("Merging %d chunk(s) with FFmpeg concat demuxer…", len(chunk_paths))

    temp_dir = os.path.dirname(chunk_paths[0])
    filelist_path = os.path.join(temp_dir, "_filelist.txt")
    output_path = os.path.join(temp_dir, "_merged_output.mp3")

    try:
        with open(filelist_path, "w", encoding="utf-8") as f:
            for fp in chunk_paths:
                abs_fp = os.path.abspath(fp).replace("\\", "/")
                safe = abs_fp.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            filelist_path,
            "-c",
            "copy",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error("FFmpeg error:\n%s", result.stderr)
            raise RuntimeError(f"FFmpeg merge failed: {result.stderr}")

        with open(output_path, "rb") as f:
            buffer = io.BytesIO(f.read())
        buffer.seek(0)

        logger.info(
            "Merge complete — output size: %.1f KB",
            buffer.getbuffer().nbytes / 1024,
        )
        return buffer

    finally:
        if os.path.isfile(filelist_path):
            try:
                os.remove(filelist_path)
            except OSError:
                pass
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass

