from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from walkthrough.api.clarification import router as clarification_router
from walkthrough.api.projects import router as projects_router
from walkthrough.api.session import router as session_router
from walkthrough.api.upload import router as upload_router

app = FastAPI(title="Walkthrough", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(projects_router)
app.include_router(clarification_router)
app.include_router(session_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Serve frontend static files in production
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        """Serve index.html for all non-API routes (SPA client-side routing)."""
        file_path = _FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_FRONTEND_DIST / "index.html")
