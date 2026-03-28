"""
Unit tests for tts_service — text chunking and language detection.

These tests do NOT make network calls; they test pure logic only.
"""

import pytest
from services.tts_service import split_text_into_chunks, detect_language


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
        # Two sentences: 3 words + 4 words = 7. With max_words=4, they
        # should be in separate chunks.
        text = "Hello world now. This is another sentence."
        chunks = split_text_into_chunks(text, max_words=4)
        assert len(chunks) == 2
        assert chunks[0] == "Hello world now."
        assert chunks[1] == "This is another sentence."

    def test_long_text_multiple_chunks(self):
        # Generate text with many sentences
        sentences = [f"Sentence number {i} is here." for i in range(50)]
        text = " ".join(sentences)
        chunks = split_text_into_chunks(text, max_words=20)
        assert len(chunks) > 1
        # Recombined text should be equivalent
        recombined = " ".join(chunks)
        assert recombined == text

    def test_single_long_sentence_exceeds_max(self):
        # A single sentence longer than max_words should still produce one
        # chunk (we don't split mid-sentence).
        words = " ".join(["word"] * 50)
        text = f"{words}."
        chunks = split_text_into_chunks(text, max_words=10)
        # The single sentence exceeds limit, but since there's nothing in
        # the current chunk when it's encountered, it gets added as one chunk.
        assert len(chunks) == 1

    def test_preserves_all_text(self):
        text = "First sentence. Second sentence! Third sentence? Fourth."
        chunks = split_text_into_chunks(text, max_words=5)
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
        # Very short nonsense — detection might fail or return something.
        # We just ensure it doesn't crash unexpectedly.
        try:
            result = detect_language("xyz")
            assert isinstance(result, str)
        except ValueError:
            pass  # acceptable — too short to detect
