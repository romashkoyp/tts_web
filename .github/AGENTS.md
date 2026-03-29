# Workspace Development Guides

This file provides development workflows, setup instructions, and practical guidance for the TTS Web project. **Start with the [project specification](./copilot-instructions.md)** for the full requirements and tech stack.

---

## Quick Reference

| Task | Command |
|------|---------|
| **Set up dev environment** | See [Local Development Setup](#local-development-setup) |
| **Start backend** | `cd backend && docker build -t tts-backend . && docker run -p 8000:8000 -v "${PWD}:/app" tts-backend` |
| **Start frontend** | `cd frontend && npm run dev` |
| **Build for production** | Frontend: `npm run build` • Backend: Docker deployment on Render |
| **Run checks** | Frontend: `npm run lint && npm run build` • Backend: `python -m pytest -q` |

---

## 1. Local Development Setup

### Prerequisites
- **Node.js** 18+ (frontend)
- **Docker** (for backend development and containerization)

### Setup Instructions

#### 1.1 Start Backend (Docker)
The backend is developed and tested inside a Docker container to ensure parity with the Render.com deployment environment. `ffmpeg` and Python dependencies are handled automatically within the image.

```bash
cd backend
# Build the Docker image
docker build -t tts-backend .

# Run the backend locally
docker run -p 8000:8000 -v "${PWD}:/app" tts-backend
```

#### 1.2 Set up Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## 2. Project Structure

```
tts_web/
├── .github/
│   ├── AGENTS.md (this file)
│   ├── copilot-instructions.md (spec)
│   └── agents/
│       └── framework-chooser.agent.md
├── backend/
│   ├── main.py (FastAPI app entry)
│   ├── services/
│   │   ├── tts_service.py (edge-tts orchestration)
│   │   └── audio_merge.py (pydub MP3 merge)
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .dockerignore
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── App.tsx (main React component)
│   │   ├── services/
│   │   │   └── api.ts (backend API client)
│   │   └── components/
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── node_modules/ (.gitignored)
│   ├── dist/ (build output, .gitignored)
│   └── tests/
├── check_edge_version.py (prototype script)
├── chunks_to_single_file.py (prototype script)
└── text_to_speech_edge.py (prototype script)
```

---

## 3. Development Workflows

### 3.1 Working on Backend TTS Service

**File locations:**
- Main app: [backend/main.py](../backend/main.py)
- TTS logic: [backend/services/tts_service.py](../backend/services/tts_service.py)
- Audio merge: [backend/services/audio_merge.py](../backend/services/audio_merge.py)

**Common tasks:**

1. **Modify chunk size or audio parameters:**
   - Edit `MAX_WORDS_PER_FILE` in [tts_service.py](../backend/services/tts_service.py)
   - Rebuild and restart container to ensure runtime parity with Render.

2. **Add a new voice or language:**
   - Reference: [edge-tts voice list](https://github.com/rany2/edge-tts#--list-voices)
   - Update voice selection logic in [tts_service.py](../backend/services/tts_service.py)
   - Update `GET /api/voices` endpoint in [main.py](../backend/main.py)

3. **Adjust MP3 bitrate/quality:**
   - Edit bitrate setting in [audio_merge.py](../backend/services/audio_merge.py)
   - Current: 48 kbps

4. **Test TTS pipeline locally:**
   ```python
   from backend.services.tts_service import process_text_to_speech
   audio_buffer = await process_text_to_speech("Your text here", "en-US", "male")
   ```

### 3.2 Working on Frontend UI

**File locations:**
- Main component: [frontend/src/App.tsx](../frontend/src/App.tsx)
- API client: [frontend/src/services/api.ts](../frontend/src/services/api.ts)
- Components: [frontend/src/components/](../frontend/src/components/)

**Common tasks:**

1. **Add a UI component (e.g., voice selector, progress bar):**
   - Create in [frontend/src/components/](../frontend/src/components/)
   - Import and use in [App.tsx](../frontend/src/App.tsx)

2. **Update form validation:**
   - Edit input handling in [App.tsx](../frontend/src/App.tsx)
   - Enforce 5MB max size and non-empty validation per spec

3. **Modify API client:**
   - Edit endpoints in [frontend/src/services/api.ts](../frontend/src/services/api.ts)
   - Match backend `POST /api/tts` and `GET /api/voices` contract

4. **Add error handling:**
   - Show user-friendly messages for:
     - Empty input
     - File too large
     - Language detection failure
     - TTS generation timeout
     - Audio merge failure

**Structure of main page:**
```
+--------------------------------------------------  +
| [Header]                                           | 
| "Long text to Speech Generator"                    |
|--------------------------------------------------  |
| [Textarea for input]                               |
| [Voice selector dropdown]                          | - active and visible only after language detection (en-US for english, en-GB for   
|                                                    |   british, etc.) and after successful GET request from backend edge-tts voice list for 
|                                                    |   the detected language
| [Submit button] - shows during TTS generation      |
| [Progress bar (time estimated) + status]           | - shows during TTS generation
| [Download link]                                    | - appears after successful generation
|--------------------------------------------------  |
| [Footer]                                           |
| "Powered by edge-tts"                              |
+--------------------------------------------------  +
```

### 3.3 Testing Workflows

**Backend tests (via Docker):**
```bash
docker exec -it <container_id> pytest tests/ -v
# Or run a temporary container for tests:
docker run --rm tts-backend pytest tests/ -v
```

**Frontend tests:**
```bash
cd frontend
npm test
# With coverage:
npm test -- --coverage
```

---

## 4. Common Debugging

### Backend Issues

| Problem | Debug Steps |
|---------|------------|
| **ffmpeg not found** | Verify `ffmpeg --version` in terminal; add to PATH if needed |
| **edge-tts timeout** | Check network; increase timeout in tts_service.py; reduce chunk size |
| **Audio merge fails** | Ensure all chunk files exist and are valid MP3; check pydub dependencies |
| **CORS errors** | Verify `CORSMiddleware` is configured in [main.py](../backend/main.py) for frontend origin |
| **Port 8000 in use** | Use `netstat -ano \| findstr :8000` (Windows) or `lsof -i :8000` (Unix) to find process |

### Frontend Issues

| Problem | Debug Steps |
|---------|------------|
| **API call hangs** | Check backend is running; verify API endpoint URLs in [api.ts](../frontend/src/services/api.ts) |
| **Download doesn't trigger** | Check browser console for errors; verify response MIME type is `audio/mpeg` |
| **Language detection fails** | Test with explicit language codes; check language detection library |
| **Vite dev server slow** | Clear `node_modules/.vite` cache; restart dev server |

---

## 5. API Contract Reference

See [copilot-instructions.md § 6](./copilot-instructions.md#6-api-contract-initial-draft) for full API spec.

### POST /api/tts
```
Request:
  - text (string, max 5MB)
   - voice_name (string, edge-tts ShortName)

Response:
  - 200: audio/mpeg (MP3 file, single merged output)
  - 400: Invalid input
  - 500: TTS or merge failed
```

### GET /api/voices
```
Query: language (string, e.g. "en-US")

Response:
   - 200: { language: "en-US", voices: [{ short_name, gender, locale }] }
  - 404: Language not supported
```

---

## 6. Deployment Checklist

Before deploying to Render.com:

- [ ] Backend: properly configured Dockerfile (installs `ffmpeg` and Python dependencies)
- [ ] Backend: CORS configured for frontend domain
- [ ] Frontend: build passes without errors (`npm run build`)
- [ ] Frontend: `.gitignore` excludes `node_modules/` and `dist/`
- [ ] Backend: `.dockerignore` excludes unnecessary files
- [ ] Environment variables: none hardcoded (use `.env` or Render config)
- [ ] Tested locally via Docker with frontend & backend both running
- [ ] Backend workflow passes (`.github/workflows/deploy-backend.yml`)
- [ ] Frontend workflow passes (`.github/workflows/deploy-frontend.yml`)
- [ ] Deploy-hook secrets set if automatic deployment is desired:
   - `RENDER_BACKEND_DEPLOY_HOOK`
   - `RENDER_FRONTEND_DEPLOY_HOOK`

See [copilot-instructions.md § 5](./copilot-instructions.md#5-deployment-requirements-render) and [deployment.md](../deployment.md) for full deployment steps.

---

## 7. Existing Prototype Scripts

These early-stage scripts are reference implementations. Integrate their logic into the backend service:

- **[text_to_speech_edge.py](../text_to_speech_edge.py)** → Move to [backend/services/tts_service.py](../backend/services/tts_service.py)
- **[chunks_to_single_file.py](../chunks_to_single_file.py)** → Move to [backend/services/audio_merge.py](../backend/services/audio_merge.py)
- **[check_edge_version.py](../check_edge_version.py)** → Reference for dependency checks

---

## 8. Key Design Decisions & Patterns

### Backend Patterns
- **Async processing:** Use `asyncio` + `concurrent.futures` for parallel chunk processing (edge-tts has no native async support per the prototype)
- **Single MP3 output:** Always merge chunks into one file for user simplicity
- **Chunking strategy:** Split by sentence/word boundaries to preserve context
- **Validation:** Validate input text for length (not null or empty) and total size (max 5MB). Enforce server-side via validate.js middleware

### Frontend Patterns
- **Textarea input:** Simple, no rich editor initially
- **Auto language detection:** Use `textcat` or similar before sending to backend
- **Progress feedback:** Show spinner + estimated time during generation
- **Single download:** Download link appears only after complete merge

### Conventions
- **Error messages:** User-friendly (no internal stack traces)
- **Error handling middleware:** catch all unhandled errors, return JSON error response
- **Configuration:** No hardcoded URLs; use environment variables
- **Logging:** Backend logs all TTS processing steps; frontend logs API errors to console

---

## 9. Operational Next Steps

1. Keep Render services on manual deploy in Render UI and trigger deploys through GitHub Actions hooks.
2. Add custom domains later only after baseline `onrender.com` deployments are stable.
3. Expand automated tests over time (backend unit tests + frontend integration coverage).

---

## 10. Asking for AI Help

When asking Copilot for code changes, mention:
- Which service (backend/frontend/scripts)
- What file you're editing  
- The desired behavior (from the spec)

Example: *"Add language detection to the React form. Frontend should send detected language to the TTS endpoint."*

---

**Last updated:** March 2026 | **Status:** Deployment-ready baseline configured for Render
