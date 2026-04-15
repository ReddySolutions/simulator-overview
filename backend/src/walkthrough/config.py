from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GCP_PROJECT_ID: str = ""
    GCS_BUCKET: str = ""
    FIRESTORE_COLLECTION: str = "walkthrough_projects"
    ANTHROPIC_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    MAX_VIDEO_SIZE_MB: int = 40
    DOCUMENTAI_PROCESSOR_ID: str = ""
    DOCUMENTAI_LOCATION: str = "us"

    model_config = {"env_prefix": ""}
