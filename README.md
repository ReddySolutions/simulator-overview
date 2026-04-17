# Walkthrough

SOP-to-Simulation Pipeline — transform call-center training videos (MP4s) and SOP PDFs into interactive, branching web simulations.

## Prerequisites

- Python 3.12+
- Node.js 20+
- GCP credentials with access to Cloud Storage, Firestore, Vertex AI, and Document AI
- Anthropic API key

## Setup

### Backend

```sh
cd backend
uv sync
```

Create a `.env` file or export environment variables:

```sh
export GCP_PROJECT_ID="your-gcp-project"
export GCS_BUCKET="your-bucket-name"
export FIRESTORE_COLLECTION="walkthrough_projects"
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_MODEL="gemini-2.0-flash"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
```

### Frontend

```sh
cd frontend
npm install
```

## Development

Start both servers in separate terminals:

```sh
# Terminal 1 — Backend (port 8000)
cd backend
uv run uvicorn walkthrough.main:app --reload --port 8000

# Terminal 2 — Frontend (port 5173)
cd frontend
npm run dev
```

The Vite dev server proxies `/api/*` requests to the backend at `localhost:8000`.

Open http://localhost:5173 in your browser.

### Docker Compose

Alternatively, run both services with Docker:

```sh
docker compose up
```

Requires a `.env` file at the project root with the environment variables listed above.

## Production Build

Build the frontend and serve it from the backend:

```sh
cd frontend
npm run build

cd ../backend
uv run uvicorn walkthrough.main:app --host 0.0.0.0 --port 8000
```

The backend serves the built frontend from `frontend/dist/` with SPA fallback routing.

## Type Checking

```sh
# Backend
cd backend
uv run pyright src/walkthrough/

# Frontend
cd frontend
npx tsc -b
```

## Architecture

- **Backend**: FastAPI + Claude Agent SDK + Vertex AI Gemini + Document AI
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS v4 + React Flow
- **Storage**: Google Cloud Storage (files) + Firestore (project state)
- **AI Pipeline**: Gemini perceives video/audio/images, Claude reasons over structured perception data
