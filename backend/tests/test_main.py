"""API tests for backend.main."""

import io
import json
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app, MAX_TEXT_BYTES


client = TestClient(app)


def test_tts_rejects_text_over_46kb() -> None:
    """POST /api/tts rejects payloads larger than MAX_TEXT_BYTES."""
    too_large_text = "a" * (MAX_TEXT_BYTES + 1)

    response = client.post(
        "/api/tts",
        json={
            "text": too_large_text,
            "voice_name": "en-US-GuyNeural",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": f"Text exceeds maximum allowed size of {MAX_TEXT_BYTES // 1024} KB."
    }


@patch("main.merge_audio_chunks")
@patch("main.process_text_to_speech", new_callable=AsyncMock)
def test_tts_streams_ndjson_events(mock_process, mock_merge) -> None:
    """POST /api/tts streams NDJSON progress lines and complete event."""
    mock_process.return_value = ["/tmp/chunk_1.mp3"]
    mock_merge.return_value = io.BytesIO(b"fake_mp3_data")

    response = client.post(
        "/api/tts",
        json={
            "text": "Hello world test text string",
            "voice_name": "en-US-GuyNeural",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")

    lines = [line.strip() for line in response.text.strip().split("\n") if line.strip()]
    assert len(lines) >= 2

    events = [json.loads(line) for line in lines]
    progress_events = [e for e in events if e.get("type") == "progress"]
    complete_events = [e for e in events if e.get("type") == "complete"]

    assert len(progress_events) > 0
    assert len(complete_events) == 1
    assert complete_events[0]["audio_base64"] == "ZmFrZV9tcDNfZGF0YQ=="  # base64("fake_mp3_data")


def test_detect_language_rejects_oversized_payload() -> None:
    """POST /api/detect-language rejects text larger than MAX_TEXT_BYTES."""
    oversized = "a" * (MAX_TEXT_BYTES + 1)
    response = client.post(
        "/api/detect-language",
        json={"text": oversized},
    )
    assert response.status_code == 400
    assert "Text exceeds maximum allowed size" in response.json()["detail"]

