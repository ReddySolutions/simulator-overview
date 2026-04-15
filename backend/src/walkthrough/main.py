from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from walkthrough.api.clarification import router as clarification_router
from walkthrough.api.projects import router as projects_router
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
