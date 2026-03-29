# TTS Web. Single-page app that turns long text into one downloadable MP3.
## https://tts-frontend-5uxc.onrender.com/

## Introduction
This is the first app I built with the agent-based workflow. Before starting the project I already had a ready Python code which I wrote before and it worked only on my machine, but I wanted to build the web app to use this TTS on the web. The main problem was that edge-tts in Node.js works only with Edge browser. I chose to preserve Python for the backend.

### Inside VS Code, agents preparation (auto choosing the models):
  1. Creating custom agent [framework-chooser](.github/agents/framework-chooser.agent.md) for choosing app framework for frontend and backend when starting a new project.
  2. After conversation with framework agent create [copilot instructions](.github/copilot-instructions.md) for all agents.
  3. Use `init` command in GitHub Copilot to create [AGENTS.md](.github/AGENTS.md) based on [copilot instructions](.github/copilot-instructions.md): development workflows, setup instructions, and practical guidance for the TTS Web project.
  4. Creating [SKILLS](.github/SKILLS.md) based on copilot instructions for specific skills like `frontend-design` used for UI design and development.
  5. Creating custom [depployment-prep-agent](.github/agents/deployment-prep-agent.agent.md) for deployment readiness checks, Render workflow/deploy updates, CI/CD, and deployment docs.

### Inside Antigravity (Claude Opus 4.6 thinking model):
  1. In agent mode to build the frontend and test it using prepared specifications, skill and instructions.
  2. Build the backend and test it using prepared specifications and instructions.
  3. Create e2e tests for the whole app using Playwright. Update instructions.

### Inside VS Code:
  1. Use [deployment prep agent](.github/agents/deployment-prep.agent.md) to prepare CI/CD workflows, adjust code, write deployment docs.
  2. Deploy the app to Render.
  3. Create a README.md with default agent.

## Tech Stack
- Frontend:
  - React
  - TypeScript
  - Vite
- Backend:
  - FastAPI (Python)
  - TTS: edge-tts (the core TTS engine, runs in backend Docker image)
  - Audio merge: pydub + ffmpeg (in backend Docker image)
  - Deployment: frontend + backend split

## Project Structure
- `frontend/`: UI, API client, Playwright E2E tests
- `backend/`: FastAPI API, TTS orchestration, merge service, pytest tests
- `.github/workflows/`: separate backend/frontend CI + optional deploy-hook trigger

## How To Run
1. Backend (Docker)
   - `cd backend`
   - `docker build -t tts-backend .`
   - `docker run -p 8000:8000 -v "${PWD}:/app" tts-backend`
2. Frontend
   - `cd frontend`
   - `npm install`
   - `npm run dev`

## Tests
- Backend unit tests: `cd backend && pytest -q`
- Frontend checks: `cd frontend && npm run lint && npm run build`
- Frontend E2E: `cd frontend && npm run test:e2e`

## CI/CD Workflow
- Backend workflow: `.github/workflows/deploy-backend.yml`
  - Runs backend tests, then triggers Render deploy hook if `RENDER_BACKEND_DEPLOY_HOOK` exists.
- Frontend workflow: `.github/workflows/deploy-frontend.yml`
  - Runs lint + build, then triggers Render deploy hook if `RENDER_FRONTEND_DEPLOY_HOOK` exists.

## Agents and Skills (in this repo setup)
### Agents
- `Deployment Prep Agent`: deploy-readiness checks, Render workflow/deploy updates, deployment docs.
- `framework-chooser`: picks framework when starting a new app.

### Skills
- `frontend-design`: used when creating/redesigning UI with intentional visual direction and non-generic styling.
