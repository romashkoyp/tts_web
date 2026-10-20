"""
Unit tests for tts_service — text chunking, chunk validation, and language detection.

These tests do NOT make network calls; they test pure logic only.
"""

import asyncio
import os
import tempfile
from unittest.mock import patch, MagicMock
import pytest
from services.tts_service import (
    split_text_into_chunks,
    detect_language,
    is_valid_chunk,
    safe_remove,
    _generate_chunk,
    process_text_to_speech,
    MIN_FILE_SIZE,
)


# ---------------------------------------------------------------------------
# is_valid_chunk
# ---------------------------------------------------------------------------

class TestIsValidChunk:
    """Tests for chunk file validation."""

    def test_nonexistent_file_returns_false(self):
        assert is_valid_chunk("nonexistent_chunk_9999.mp3") is False

    def test_empty_or_small_file_returns_false(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"12345")  # only 5 bytes < MIN_FILE_SIZE
            tmp_path = f.name
        try:
            assert is_valid_chunk(tmp_path) is False
        finally:
            os.remove(tmp_path)

    def test_valid_file_returns_true(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"x" * (MIN_FILE_SIZE + 10))
            tmp_path = f.name
        try:
            assert is_valid_chunk(tmp_path) is True
        finally:
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# split_text_into_chunks
# ---------------------------------------------------------------------------

class TestSplitTextIntoChunks:
    """Tests for the text chunking function."""

    def test_empty_string_returns_empty_list(self):
        assert split_text_into_chunks("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert split_text_into_chunks("   \n\t  ") == []

    def test_short_text_single_chunk(self):
        text = "Hello world. This is a test."
        chunks = split_text_into_chunks(text, max_words=100)
        assert len(chunks) == 1
        assert chunks[0] == text.strip()

    def test_splits_at_sentence_boundary(self):
        text = "Hello world now. This is another sentence."
        chunks = split_text_into_chunks(text, max_words=4)
        assert len(chunks) == 2
        assert chunks[0] == "Hello world now."
        assert chunks[1] == "This is another sentence."

    def test_paragraph_breaks_and_formatting(self):
        text = "First paragraph sentence.\n\nSecond paragraph sentence."
        chunks = split_text_into_chunks(text, max_words=3)
        assert len(chunks) == 2
        assert chunks[0] == "First paragraph sentence."
        assert chunks[1] == "Second paragraph sentence."

    def test_preserves_single_newlines(self):
        text = "Line one\nLine two"
        chunks = split_text_into_chunks(text, max_words=100)
        assert len(chunks) == 1
        assert chunks[0] == "Line one\nLine two"

    def test_splits_oversized_sentence_by_clauses(self):
        text = "This is clause one, and this is clause two, while this is clause three."
        # Limit to 5 words per chunk, so clauses will be grouped/split
        chunks = split_text_into_chunks(text, max_words=5)
        assert len(chunks) > 1
        assert "This is clause one," in chunks[0]

    def test_cyrillic_multilingual_sentence_boundaries(self):
        text = "Привет мир! Это предложение на русском языке. «Цитирование текста» работает."
        chunks = split_text_into_chunks(text, max_words=6)
        assert len(chunks) == 3
        assert chunks[0] == "Привет мир!"
        assert chunks[1] == "Это предложение на русском языке."
        assert chunks[2] == "«Цитирование текста» работает."

    def test_long_text_multiple_chunks(self):
        sentences = [f"Sentence number {i} is here." for i in range(50)]
        text = " ".join(sentences)
        chunks = split_text_into_chunks(text, max_words=20)
        assert len(chunks) > 1
        recombined = " ".join(chunks)
        assert recombined == text


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    """Tests for language detection."""

    def test_english_text(self):
        locale = detect_language(
            "The quick brown fox jumps over the lazy dog. "
            "This is a simple English sentence for testing."
        )
        assert locale.startswith("en")

    def test_russian_text(self):
        locale = detect_language(
            "Привет мир. Это простое предложение на русском языке для тестирования."
        )
        assert locale == "ru-RU"

    def test_german_text(self):
        locale = detect_language(
            "Dies ist ein einfacher deutscher Satz zum Testen. "
            "Die Sprache sollte korrekt erkannt werden."
        )
        assert locale == "de-DE"

    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="Could not detect language"):
            detect_language("")

    def test_nonsense_short_text_raises_or_detects(self):
        try:
            result = detect_language("xyz")
            assert isinstance(result, str)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# safe_remove
# ---------------------------------------------------------------------------

class TestSafeRemove:
    """Tests for safe_remove helper."""

    def test_safe_remove_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"data")
            path = f.name
        assert os.path.exists(path)
        safe_remove(path)
        assert not os.path.exists(path)

    def test_safe_remove_nonexistent_file(self):
        # Should not raise exception
        safe_remove("nonexistent_file_12345.mp3")


# ---------------------------------------------------------------------------
# _generate_chunk & process_text_to_speech (Native Async & Atomic Writes)
# ---------------------------------------------------------------------------

class TestGenerateChunkAndPipeline:
    """Tests for native async generation and atomic write safety."""

    @pytest.mark.asyncio
    async def test_generate_chunk_atomic_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            semaphore = asyncio.Semaphore(2)

            async def mock_save(path: str):
                with open(path, "wb") as f:
                    f.write(b"a" * (MIN_FILE_SIZE + 50))

            with patch("edge_tts.Communicate") as mock_comm_cls:
                instance = MagicMock()
                instance.save = mock_save
                mock_comm_cls.return_value = instance

                done_called = False
                def on_done():
                    nonlocal done_called
                    done_called = True

                result_path = await _generate_chunk(
                    index=0,
                    text="Hello test chunk",
                    voice="en-US-GuyNeural",
                    output_dir=temp_dir,
                    total_chunks=1,
                    semaphore=semaphore,
                    on_chunk_done=on_done,
                )

                assert result_path.endswith("chunk_0000.mp3")
                assert os.path.isfile(result_path)
                assert not os.path.isfile(result_path + ".tmp")
                assert done_called is True

    @pytest.mark.asyncio
    async def test_generate_chunk_cleans_tmp_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            semaphore = asyncio.Semaphore(1)

            async def mock_save_too_small(path: str):
                with open(path, "wb") as f:
                    f.write(b"too small")

            with patch("edge_tts.Communicate") as mock_comm_cls, \
                 patch("services.tts_service.MAX_RETRIES", 1):
                instance = MagicMock()
                instance.save = mock_save_too_small
                mock_comm_cls.return_value = instance

                with pytest.raises(RuntimeError, match="failed after 1 attempts"):
                    await _generate_chunk(
                        index=0,
                        text="Fail chunk",
                        voice="en-US-GuyNeural",
                        output_dir=temp_dir,
                        total_chunks=1,
                        semaphore=semaphore,
                    )

                tmp_path = os.path.join(temp_dir, "chunk_0000.mp3.tmp")
                final_path = os.path.join(temp_dir, "chunk_0000.mp3")
                assert not os.path.exists(tmp_path)
                assert not os.path.exists(final_path)

    @pytest.mark.asyncio
    async def test_process_text_to_speech_full_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            async def mock_save(path: str):
                with open(path, "wb") as f:
                    f.write(b"a" * (MIN_FILE_SIZE + 50))

            with patch("edge_tts.Communicate") as mock_comm_cls:
                instance = MagicMock()
                instance.save = mock_save
                mock_comm_cls.return_value = instance

                progress_calls = []
                def on_progress(pct: int, status: str):
                    progress_calls.append((pct, status))

                paths = await process_text_to_speech(
                    text="First sentence here. Second sentence here.",
                    voice="en-US-GuyNeural",
                    temp_dir=temp_dir,
                    on_progress=on_progress,
                )

                assert len(paths) >= 1
                for p in paths:
                    assert os.path.isfile(p)
                    assert p.endswith(".mp3")
                    assert not os.path.exists(p + ".tmp")
                assert len(progress_calls) >= 2


class TestVoicesCache:
    """Tests for in-memory TTL voice caching."""

    @pytest.mark.asyncio
    async def test_get_voices_uses_cache(self):
        from unittest.mock import AsyncMock
        import services.tts_service as tts_mod

        mock_voices = [
            {"ShortName": "en-US-GuyNeural", "Gender": "Male", "Locale": "en-US"},
            {"ShortName": "en-US-JennyNeural", "Gender": "Female", "Locale": "en-US"},
        ]
        with patch("edge_tts.list_voices", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_voices
            tts_mod._voices_cache = None
            tts_mod._voices_cache_timestamp = 0.0

            res1 = await tts_mod.get_voices_for_language("en-US")
            res2 = await tts_mod.get_voices_for_language("en-US")

            assert len(res1) == 2
            assert len(res2) == 2
            mock_list.assert_called_once()


class TestAbbreviationChunking:
    """Tests that abbreviations with periods do not cause premature splits."""

    def test_preserves_common_titles_and_abbreviations(self):
        text = "Dr. Smith and Mr. Jones went to the lab. They met Prof. Miller there."
        chunks = split_text_into_chunks(text, max_words=50)
        assert len(chunks) == 1
        assert "Dr. Smith" in chunks[0]
        assert "Mr. Jones" in chunks[0]
        assert "Prof. Miller" in chunks[0]


