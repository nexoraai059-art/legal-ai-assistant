from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Legal AI Assistant"
    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    llm_api_key: str = ""
    llm_model: str = ""
    embedding_api_key: str = ""
    embedding_api_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    data_dir: Path = BACKEND_DIR / "data"
    max_upload_mb: int = 15
    max_pdf_pages: int = 500

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()