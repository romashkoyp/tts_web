"""
Unit tests for tts_service — text chunking, chunk validation, and language detection.

These tests do NOT make network calls; they test pure logic only.
"""

import os
import tempfile
import pytest
from services.tts_service import (
    split_text_into_chunks,
    detect_language,
    is_valid_chunk,
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

