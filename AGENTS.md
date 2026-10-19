# AGENTS.md — Python & Web Project Context

## 1. Tech Stack & Environment
- **Python Version:** Python 3.12+ (base container: `python:3.12-slim-bookworm` in `backend/Dockerfile`).
- **Environment & Package Manager:**
  - **Backend:** `pip` with `backend/requirements.txt` (local venv e.g. `.venv` or containerized execution).
  - **Frontend:** `npm` (v11+) with Node.js 20+ managing `frontend/package.json` and `package-lock.json`.
  - **Containerization:** Docker & Docker Desktop for development parity and Render deployment.
- **GUI / Frontend Framework:** React 19 (`^19.2.4`) Single Page Application (SPA) with TypeScript and Vite 8 (`^8.0.1`). *(Note: The repository is architected as a web app with a FastAPI backend; it does not use a native desktop toolkit like PyQt/PySide, though a standalone Python CLI generator `audiobook.py` is included for direct terminal use).*
- **Architecture Pattern:** Client-Server / Service-Oriented Single Page Application:
  - **Frontend:** Declarative, component-driven React architecture with a centralized API service layer (`frontend/src/services/api.ts`).
  - **Backend:** Layered FastAPI service separating route definitions (`backend/main.py`) from business logic and audio pipelines (`backend/services/tts_service.py`, `backend/services/audio_merge.py`).
- **Local Storage & Config:**
  - **State & Storage:** Stateless request lifecycle; no persistent database. Audio processing creates isolated temporary directories (`tempfile.mkdtemp(prefix="tts_chunks_")`) that are automatically cleaned up in `try...finally` blocks.
  - **Configuration:** Environment variables (`CORS_ORIGINS`, `PORT`, `VITE_API_URL`) managed via `.env` files and Render environment settings.
- **Packaging & Distribution:**
  - **Backend:** Docker container image (`python:3.12-slim-bookworm` with system `ffmpeg` installed) deployed as a Render Web Service.
  - **Frontend:** Static asset bundle built via Vite (`npm run build` -> `frontend/dist/`) deployed as a Render Static Site.
  - **CLI Prototype:** `audiobook.py` executable directly via standard Python interpreter.

## 2. Directory Structure & Key Modules
- **Entry Points:**
  - `backend/main.py` — FastAPI application entry point (`app` instance, CORS middleware, API route handlers).
  - `frontend/src/main.tsx` & `frontend/src/App.tsx` — React DOM mount and primary SPA state/view orchestrator.
  - `audiobook.py` — Standalone terminal-based prototype script for text-to-MP3 generation.
- `frontend/src/components/` — UI components and scoped CSS stylesheets:
  - `TextInput.tsx`: Text input area with paste handling and 46 KB client-side validation.
  - `VoiceSelector.tsx`: Dropdown for voice gender/style variants based on detected language.
  - `ProgressIndicator.tsx`: Real-time percentage progress bar and status message display.
  - `DownloadLink.tsx`: Audio player preview and single MP3 download trigger.
  - `Header.tsx` & `Footer.tsx`: Branding and footer attribution.
- `frontend/src/services/` — Frontend networking layer:
  - `api.ts`: API client for language detection (`POST /api/detect-language`), voice queries (`GET /api/voices`), and NDJSON streaming text-to-speech generation (`POST /api/tts`).
- `backend/services/` — Core business logic and audio processing:
  - `tts_service.py`: Text chunking (`split_text_into_chunks`), language identification (`detect_language` via `langdetect`), voice listing (`get_voices_for_language`), and multi-worker speech synthesis (`process_text_to_speech` via `edge_tts`).
  - `audio_merge.py`: Chunk concatenation (`merge_audio_chunks`) using FFmpeg's concat demuxer (`-f concat -c copy`) into an in-memory `io.BytesIO` MP3 buffer.
- `assets/ or resources/`:
  - `frontend/public/` — Static browser assets (icons, favicon, web manifest).
  - `frontend/src/assets/` — Bundled frontend media assets.
  - `Within-The-Tides.txt` — Reference sample text file for generation testing.

## 3. GUI & Concurrency Conventions
- **UI Definition Style:** Declarative TSX (React 19) components with responsive, modular vanilla CSS (`App.css`, `index.css`, and component `.css` files).
- **Main Thread / Event Loop Rule:**
  - **Backend Event Loop:** Never block FastAPI's `asyncio` event loop with synchronous file I/O, heavy chunking, or blocking network calls. `edge-tts` generation runs concurrently inside a `ThreadPoolExecutor(max_workers=20)` wrapped via `loop.run_in_executor()`.
  - **Frontend UI Thread:** The browser UI remains responsive during generation by processing streaming server responses asynchronously via `ReadableStreamDefaultReader` on the NDJSON stream without freezing UI paint cycles.
- **Concurrency & Signals / Event Streaming:**
  - **Backend Pipeline Concurrency:** `asyncio.Queue` bridges chunk generation workers to the HTTP response stream. Each worker executes with exponential backoff retries (`MAX_RETRIES = 3`, 2-second base backoff).
  - **Real-Time Event Streaming:** `POST /api/tts` returns a `StreamingResponse` (`application/x-ndjson`). Real-time progress events (`{"type": "progress", "percent": N, "status": "..."}`) stream incrementally to the client, concluding with a final completion event containing the base64-encoded audio payload (`{"type": "complete", "audio_base64": "..."}`).
- **Styling & Theming:** Custom modern dark theme featuring glassmorphism accents, vibrant gradient highlights, accessible typography, and smooth CSS keyframe transitions for progress indicators and inputs.
- **Resource & Temp File Paths:**
  - Audio chunk files are generated in ephemeral directories created via `tempfile.mkdtemp(prefix="tts_chunks_")`.
  - All temporary files (including intermediate chunks, `_filelist.txt`, and `_merged_output.mp3`) are strictly removed in `try...finally` blocks and `shutil.rmtree` handlers to prevent storage leaks.

## 4. Development, Build & Packaging Commands
*(Always run inside the project virtual environment or respective service directory)*
- **Run Backend (Dev - Docker):**
  ```bash
  cd backend
  docker build -t tts-backend .
  docker run -p 8000:8000 -v "${PWD}:/app" tts-backend
  ```
- **Run Backend (Dev - Local venv):**
  ```bash
  cd backend
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
  ```
- **Run Frontend (Dev):**
  ```bash
  cd frontend
  npm run dev
  ```
- **Build Frontend (Production):**
  ```bash
  cd frontend
  npm run build
  # Runs `tsc -b && vite build` -> outputs optimized static assets to `frontend/dist/`
  ```
- **Build Standalone / Backend Container:**
  ```bash
  cd backend
  docker build -t tts-backend .
  ```
- **Run Tests:**
  - **Backend Unit Tests:** `cd backend && pytest -q`
  - **Frontend E2E Tests:** `cd frontend && npm run test:e2e` (runs Playwright test suite)
- **Linter & Formatter:**
  - **Frontend:** `cd frontend && npm run lint` (ESLint 9 + typescript-eslint)
  - **Backend:** `pytest -q` or `ruff check backend/`

## 5. Testing & Mocking Guidelines
- **Test Frameworks:**
  - **Backend:** `pytest` (8.0+), `pytest-asyncio`, `httpx` (FastAPI `TestClient`), and `unittest.mock` (`patch`, `AsyncMock`).
  - **Frontend:** `@playwright/test` for end-to-end user experience and stream simulation.
- **Backend Mocking Rules:**
  - Isolate external network dependencies: Mock `edge_tts.Communicate`, `main.process_text_to_speech`, and `main.merge_audio_chunks` during API integration tests (`backend/tests/test_main.py`).
  - Unit tests in `backend/tests/test_tts_service.py` test pure algorithmic logic (text chunking boundaries, chunk file validation, language code mapping) without making live external API requests.
- **Frontend E2E Testing Rules:**
  - Playwright routes intercept `/api/detect-language`, `/api/voices*`, and `/api/tts` to supply mock NDJSON chunk streams and mock base64 audio without requiring a running backend instance.
  - Web Audio API (`AudioContext`) is mocked in `frontend/tests/tts-flow.spec.ts` to deterministically validate duration calculations and audio player playback triggers.

## 6. Guardrails & Do-Nots
- **Payload Size Limits:** Strictly enforce the 46 KB text payload limit (`MAX_TEXT_BYTES = 46 * 1024`) on `POST /api/tts`. Oversized inputs must immediately be rejected with HTTP 400 before triggering speech synthesis.
- **No Direct Voice ID Selection:** Users select high-level language variants and gender styles (e.g., Male/Female); do not expose raw Microsoft Edge TTS voice identifiers directly in the primary user flow.
- **Never Block Main Event Loops:** Keep async route handlers non-blocking. Offload all subprocess invocations (`ffmpeg`) and edge-tts chunk synthesis to background worker pools.
- **Temp Directory Hygiene:** Ensure temporary directories are created per request and unconditionally purged in `finally` blocks, even if processing raises an exception.
- **Cross-Platform / OS Paths:** Always construct filesystem paths using `os.path.join()` or `pathlib.Path`. When writing FFmpeg concat demuxer lists (`filelist.txt`), normalize Windows backslashes (`\`) to forward slashes (`/`) and escape single quotes to prevent demuxer failures across operating systems.

## 7. Folder Structure and Description
```
tts_web/
├── .github/
│   ├── agents/                   # Custom agent configurations (deployment-prep, framework-chooser)
│   ├── workflows/                # GitHub Actions CI/CD pipelines
│   │   ├── deploy-backend.yml    # Backend test suite and Render deploy hook trigger
│   │   └── deploy-frontend.yml   # Frontend lint, build, and Render deploy hook trigger
│   ├── AGENTS.md                 # Workspace guidance and instructions for Copilot agents
│   └── copilot-instructions.md   # Core project specification and technical requirements
├── backend/                      # FastAPI Python backend service
│   ├── services/
│   │   ├── __init__.py
│   │   ├── audio_merge.py        # FFmpeg concat demuxer audio merge service
│   │   └── tts_service.py        # edge-tts chunking, voice lookup, and speech generation
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_main.py          # FastAPI endpoint integration tests
│   │   └── test_tts_service.py   # Chunking, validation, and language detection unit tests
│   ├── .dockerignore             # Docker build exclusion rules
│   ├── .env.example              # Template for backend environment variables (CORS_ORIGINS)
│   ├── Dockerfile                # Production Docker image with Python 3.12 & FFmpeg
│   ├── main.py                   # FastAPI application entry point, CORS, routes & streaming
│   └── requirements.txt          # Python dependencies (FastAPI, uvicorn, edge-tts, etc.)
├── frontend/                     # React 19 + TypeScript + Vite frontend SPA
│   ├── public/                   # Static public assets (favicons, manifest)
│   ├── src/
│   │   ├── assets/               # Bundled images and media assets
│   │   ├── components/           # Modular React UI components
│   │   │   ├── DownloadLink.tsx  # Audio player preview and MP3 download button
│   │   │   ├── Footer.tsx        # Footer with edge-tts attribution
│   │   │   ├── Header.tsx        # Application title and subtitle header
│   │   │   ├── ProgressIndicator.tsx # Visual progress bar with status text
│   │   │   ├── TextInput.tsx     # Textarea input with length validation
│   │   │   └── VoiceSelector.tsx # Voice variant and gender selector dropdown
│   │   ├── services/
│   │   │   └── api.ts            # Typed HTTP client with NDJSON streaming reader
│   │   ├── App.css               # App-level styling and layout rules
│   │   ├── App.tsx               # Primary React component and state coordinator
│   │   ├── index.css             # Global styling, tokens, and CSS resets
│   │   └── main.tsx              # React application entry point (DOM root mount)
│   ├── tests/
│   │   └── tts-flow.spec.ts      # Playwright end-to-end tests for user flow and streaming
│   ├── .env.example              # Template for frontend environment variables (VITE_API_URL)
│   ├── eslint.config.js          # ESLint 9 configuration
│   ├── package.json              # Frontend npm dependencies and scripts
│   ├── playwright.config.ts      # Playwright test configuration
│   ├── tsconfig.json             # TypeScript project configuration
│   └── vite.config.ts            # Vite bundler configuration
├── audiobook.py                  # Standalone CLI script prototype for text-to-MP3 generation
├── deployment.md                 # Deployment documentation and Render setup instructions
├── README.md                     # Project overview, architecture, and quickstart guide
└── Within-The-Tides.txt          # Sample text file used for TTS generation testing
```
