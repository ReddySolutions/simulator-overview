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

    # QA / LLM critic settings (default off — new code paths stay behind this flag)
    QA_ENABLE_LLM_CRITIC: bool = False
    QA_BLOCK_ON_CRITICAL: bool = False
    NARRATIVE_FIDELITY_MODEL: str = "claude-haiku-4-5-20251001"
    CONTRADICTION_CRITIC_MODEL: str = "claude-sonnet-4-6"

    model_config = {"env_prefix": "", "env_file": ".env"}
