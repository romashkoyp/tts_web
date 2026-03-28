# Project Specification: Web Text-to-Speech Tool

## 1. Project Overview
Build a single-page web application that converts long plain text into one downloadable MP3 file.

The frontend is a React SPA where users can:
- paste plain text directly.

The backend is a FastAPI service that processes text-to-speech generation using `edge-tts`, splits large input into chunks, merges chunks into one MP3, and returns the final file.

## 2. Tech Stack
- Frontend: React (TypeScript) with Vite
- Backend: FastAPI (Python)
- TTS engine: `edge-tts`
- Audio merge: `pydub`
- Audio backend dependency: `ffmpeg` (installed in Docker image)
- Deployment target: Render.com (Backend via Docker Container)

## 3. Core Functional Requirements

### 3.1 Input
- User can provide source text by pasting text into a textarea.
- App validates that text is not empty and does not exceed a reasonable size (e.g., 5 megabytes) or equal length.

### 3.2 Voice and Language Selection
- App detects language from provided text.
- User does not choose exact voice ID.
- User can choose only a variation/style among voices for the detected language (for example male/female or available language-specific variants from egde-tts).

### 3.3 TTS Processing
- Backend splits text into manageable chunks by sentence/word limit.
- Backend generates chunk audio asynchronously using `edge-tts`.
- Backend merges all generated chunks into one MP3 file.
- Output is always a single downloadable MP3 for each request.

### 3.4 Output
- Frontend receives processed audio and triggers browser download.
- Only one final MP3 is presented to the user.

## 4. Non-Functional Requirements
- Single-page user experience.
- No user accounts or authentication.
- Session-based usage only (no user history persistence required).
- Clear progress indicator during generation.
- Error handling for:
	- invalid/empty input,
	- TTS generation failures,
	- merge/export failures.

## 5. Deployment Requirements (Render)

### 5.1 Preferred Deployment Model
Deploy separately:
- backend, developed and deployed in a Docker container (FastAPI serves API endpoints).
- frontend, serves compiled React static assets.

### 5.2 Runtime Requirements
- Backend runs as a Docker container.
- Python runtime with project dependencies inside the Docker image.
- System package `ffmpeg` installed in the Docker image.
- CORS configured if frontend and backend are split into separate services.

## 6. API Contract (Initial Draft)
- `POST /api/tts`
	- Input: text payload + selected variation option.
	- Output: `audio/mpeg` (single MP3 file).
- `GET /api/voices`
	- Input: detected language code.
	- Output: available language-specific variation options.

## 7. Initial Project Structure
- `frontend/` React app
- `frontend/static/` built frontend artifacts
- `backend/` FastAPI app
- `backend/services/tts_service.py` chunking + edge-tts orchestration
- `backend/services/audio_merge.py` MP3 concatenation via pydub

## 8. Out of Scope (v1)
- User login/account management
- Saved conversion history
- Multi-file batch processing
- Editing/previewing generated audio timeline

## 9. Success Criteria
- User can paste text.
- Language detection and variation selection work reliably.
- App generates and downloads exactly one MP3 file per request.
- App is successfully deployed and usable on Render.com.
