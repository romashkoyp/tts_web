"""API tests for backend.main."""

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
