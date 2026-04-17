from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Local dev mode — bypasses all GCP services
    LOCAL_DEV: bool = False
    LOCAL_DATA_DIR: str = "data"

    # GCP settings (ignored when LOCAL_DEV=true)
    GCP_PROJECT_ID: str = ""
    GCS_BUCKET: str = ""
    FIRESTORE_COLLECTION: str = "walkthrough_projects"
    DOCUMENTAI_PROCESSOR_ID: str = ""
    DOCUMENTAI_LOCATION: str = "us"

    # AI settings
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""  # Google AI Studio key (local dev)
    GEMINI_MODEL: str = "gemini-2.0-flash"
    MAX_VIDEO_SIZE_MB: int = 40

    # QA phase settings (US-010)
    QA_BLOCK_ON_CRITICAL: bool = False

    model_config = {"env_prefix": "", "env_file": ".env"}
