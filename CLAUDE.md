# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Walkthrough** — SOP-to-Simulation pipeline. Turns call-center training videos (MP4 + narration) and SOP PDFs into an interactive, branching React SPA. Minimum input is **at least one MP4 and at least one PDF** — the core value comes from cross-referencing three independent sources (video, audio transcript, PDF), so single-source uploads are rejected at the API layer. See `SPEC.md` for the full product spec; `data-flow.md` has the pipeline diagram.

## Common commands

### Backend (Python 3.12, `uv`)
```sh
cd backend
uv sync                                                    # install deps
uv run uvicorn walkthrough.main:app --reload --port 8000   # dev server
uv run pyright src/walkthrough/                            # typecheck
uv run pytest                                              # all tests
uv run pytest tests/test_orchestrator_qa_phase.py          # single file
uv run pytest -k test_resume                               # by name
uv run pytest -m 'not integration'                         # skip live-Gemini tests
```
`pytest.ini_options` sets `asyncio_mode = "auto"` — async tests do not need `@pytest.mark.asyncio`. Tests marked `integration` hit the live Gemini API; skip them by default in CI.

### Frontend (Node 20+, npm)
```sh
cd frontend
npm install
npm run dev          # Vite on :5173, proxies /api + /health to :8000
npm run build        # tsc -b && vite build → frontend/dist/
npm run lint         # eslint
npx tsc -b           # typecheck only
```

### Full stack
```sh
docker compose up                                          # both services + .env at repo root
```
Production build: `npm run build` in `frontend/`, then run uvicorn — `backend/src/walkthrough/main.py` mounts `frontend/dist/` with SPA fallback, so the backend serves the built SPA on the same port.

## LOCAL_DEV mode (important)

The backend has two modes, selected by the `LOCAL_DEV` env var (see `backend/src/walkthrough/config.py`). The committed `backend/.env` sets `LOCAL_DEV=true`, which is the default development path:

- `LOCAL_DEV=true` — zero GCP dependencies. `backend/src/walkthrough/deps.py` swaps in `LocalStorageClient` (files under `LOCAL_DATA_DIR`, default `./data`) and `LocalFirestoreClient` (JSON on disk). AI calls use `local_gemini_video.py` / `local_gemini_screenshot.py` / `local_pdf.py` with `GEMINI_API_KEY` (Google AI Studio) instead of Vertex AI SDK.
- `LOCAL_DEV=false` — real GCP. Requires `GCP_PROJECT_ID`, `GCS_BUCKET`, `GOOGLE_APPLICATION_CREDENTIALS`, `DOCUMENTAI_PROCESSOR_ID`, plus the `gcp` optional-deps install (`uv sync --extra gcp`).

**Never hardcode a client** — always go through `get_storage_client()` / `get_firestore_client()` in `deps.py` so LOCAL_DEV keeps working. When adding a new external service, follow the same `ServiceClient` + `LocalServiceClient` pattern.

## Architecture

### Dual-model AI (the central design choice)
- **Gemini (perception)** — runs on raw media. Sees each MP4 in one pass, emits keyframes + UI-state-per-keyframe + transitions + timestamped transcript. Also classifies PDF-extracted images. Document AI (or local `pymupdf` in LOCAL_DEV) handles PDF structure.
- **Claude Agent SDK (reasoning)** — never sees the video/audio directly, only Gemini's structured output. Does path-merging, narrative synthesis, three-way contradiction detection, clarification-question generation, and final code generation.

Agents live in `backend/src/walkthrough/ai/`. Tool implementations are in `ai/tools/`. A single stateful agent drives the whole pipeline (not multi-agent) — see `ai/agent.py` and `ai/orchestrator.py`.

### Pipeline orchestration
`PhaseOrchestrator` in `ai/orchestrator.py` drives 8 phases in order, defined by `PHASE_ORDER` in `storage/phase_artifacts.py`:
```
ingestion → path_merge → narrative → contradictions → clarification → generation → qa
```
After each phase, the orchestrator:
1. Writes a JSON **phase artifact** under `data/projects/<project_id>/phases/<phase>.json` via `write_phase_artifact()`.
2. Persists the updated `Project` model to Firestore (or local equivalent).
3. Yields a `ProgressEvent` for SSE streaming to the frontend.

**Resume works by artifact presence**, not a status column — if `phases/narrative.json` exists, narrative is considered done and is skipped on resume. Do not short-circuit this by writing `project.status` alone; always write the artifact. The orchestrator pauses after `clarification` to wait for user input via the clarification API.

### Backend request → pipeline flow
1. `api/upload.py` — receives MP4/PDF, persists via storage client.
2. `api/projects.py` — `POST /api/projects/{id}/analyze` launches `_run_pipeline_task` as a background `asyncio.Task`, pushing `ProgressEvent`s onto an in-memory queue keyed by `project_id`.
3. `api/projects.py` — `GET /api/projects/{id}/progress` consumes that queue and relays SSE events. The queue is **in-process only**; a uvicorn restart mid-run drops in-flight progress (resume still works because artifacts are on disk).
4. `api/clarification.py` — answers pause/resume the pipeline between phases 6 and 7.
5. `api/session.py` — session resumption (M8): user closes tab mid-clarify, returns later.

### Frontend architecture
- `src/pages/` — one page per pipeline stage: `UploadPage`, `ProgressPage` (SSE consumer), `ClarificationPage`, `WalkthroughPage`, plus `ProjectListPage`.
- `src/api/client.ts` — single `request<T>()` helper against `BASE = "/api"`; Vite proxy routes it to `:8000` in dev.
- `src/components/RoutingDiagram.tsx` + `SubDiagram.tsx` — React Flow (`@xyflow/react` + `@dagrejs/dagre`) render the decision tree; `WireframeScreen` renders keyframe-derived wireframes; `NarrativePanel` shows the audio+PDF "why" panel.
- Routing is `react-router` v7. No global state library — each page fetches what it needs.

## Project-specific gotchas

- **MP4s are the backbone, PDFs are supplementary context.** When ambiguity arises between them, the video is usually authoritative for *what happened*, the PDF for *what should happen*. Neither is unconditionally trusted — contradictions must be surfaced, not adjudicated (see `SPEC.md` N4).
- **Decision-tree self-loops are a known class of bug.** Generation sometimes produces branch paths that loop back to the same screen; the fix lives upstream in the merge/generation prompts (`ai/tools/generate.py`, `ai/agent.py`), not in frontend rendering.
- **Workflow/decision-tree data is never compressed between phases** (`SPEC.md` M6/N5). Narrative text can be summarized; structural data cannot — lossy compression produces hallucinated branches.
- **Every piece of generated content must cite a source** (video timestamp, audio excerpt, or PDF section — `SPEC.md` M7). When adding generation logic, preserve and propagate source references.
- **CORS is hardcoded** to `http://localhost:5173` / `:3000` in `main.py`. Changing the frontend dev port means editing CORS.

## Writing tests

Backend: add to `backend/tests/` as `test_*.py`. Use the existing `conftest.py` fixtures (project factories, storage/firestore shims). Use `-m integration` for anything that hits real Gemini. After fixing a bug, always add a regression test that would have caught it — frontend-only fixes often still warrant a backend-level regression test if the bug touched the API surface.

## Workflow conventions

- Follow Python rule in `~/.claude/CLAUDE.md`: no f-strings without placeholders.
- Prefer `rg` over `grep`, `fd` over `find` for shell work.
- Always end responses with a 1–2 sentence recap (what changed, what's next).
