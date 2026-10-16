from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Legal AI Assistant"
    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    llm_api_key: str = ""
    llm_model: str = ""
    data_dir: Path = BACKEND_DIR / "data"
    max_upload_mb: int = 15
    max_pdf_pages: int = 500

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()