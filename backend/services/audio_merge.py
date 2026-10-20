"""
Audio Merge Service — concatenate chunk MP3 files into a single output using FFmpeg.

Adapted from audiobook.py.
"""

import asyncio
import io
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def _write_filelist(filelist_path: str, chunk_paths: list[str]) -> None:
    """Write FFmpeg concat demuxer file list with safe escaped paths."""
    with open(filelist_path, "w", encoding="utf-8") as f:
        for fp in chunk_paths:
            abs_fp = os.path.abspath(fp).replace("\\", "/")
            safe = abs_fp.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")


def _read_output_to_buffer(output_path: str) -> io.BytesIO:
    with open(output_path, "rb") as f:
        buffer = io.BytesIO(f.read())
    buffer.seek(0)
    return buffer


def _cleanup_files(paths: list[str]) -> None:
    for path in paths:
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


async def merge_audio_chunks_async(
    chunk_paths: list[str], remove_source_chunks: bool = True
) -> io.BytesIO:
    """
    Asynchronously merge chunk MP3 files from *chunk_paths* (in order) using
    FFmpeg's concat demuxer without blocking the FastAPI asyncio event loop.

    Optionally deletes source chunks immediately after a successful merge to
    reclaim disk/tmpfs memory early.
    """
    if not chunk_paths:
        raise ValueError("No chunk files to merge")

    logger.info("Merging %d chunk(s) asynchronously with FFmpeg…", len(chunk_paths))

    temp_dir = os.path.dirname(chunk_paths[0])
    filelist_path = os.path.join(temp_dir, "_filelist.txt")
    output_path = os.path.join(temp_dir, "_merged_output.mp3")

    try:
        await asyncio.to_thread(_write_filelist, filelist_path, chunk_paths)

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

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            logger.error("FFmpeg error:\n%s", stderr_text)
            raise RuntimeError(f"FFmpeg merge failed: {stderr_text}")

        # Eagerly purge intermediate source chunks right after merge to reclaim RAM /tmpfs
        if remove_source_chunks:
            await asyncio.to_thread(_cleanup_files, chunk_paths)

        buffer = await asyncio.to_thread(_read_output_to_buffer, output_path)

        logger.info(
            "Async merge complete — output size: %.1f KB",
            buffer.getbuffer().nbytes / 1024,
        )
        return buffer

    finally:
        await asyncio.to_thread(_cleanup_files, [filelist_path, output_path])


def merge_audio_chunks(chunk_paths: list[str]) -> io.BytesIO:
    """
    Synchronous merge chunk MP3 files from *chunk_paths* using FFmpeg's concat demuxer.
    Preserved for CLI prototypes, offline processing, and unit tests.
    """
    if not chunk_paths:
        raise ValueError("No chunk files to merge")

    logger.info("Merging %d chunk(s) with FFmpeg concat demuxer…", len(chunk_paths))

    temp_dir = os.path.dirname(chunk_paths[0])
    filelist_path = os.path.join(temp_dir, "_filelist.txt")
    output_path = os.path.join(temp_dir, "_merged_output.mp3")

    try:
        _write_filelist(filelist_path, chunk_paths)

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

        buffer = _read_output_to_buffer(output_path)

        logger.info(
            "Merge complete — output size: %.1f KB",
            buffer.getbuffer().nbytes / 1024,
        )
        return buffer

    finally:
        _cleanup_files([filelist_path, output_path])
