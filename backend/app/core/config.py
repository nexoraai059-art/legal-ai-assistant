from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Legal AI Assistant"
    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    jwt_secret_key: str = ""
    access_token_minutes: int = 60
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_minutes: int = 15
    llm_api_key: str = ""
    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    embedding_api_key: str = ""
    embedding_api_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    data_dir: Path = BACKEND_DIR / "data"
    max_upload_mb: int = 15
    max_pdf_pages: int = 500
    ocr_enabled: bool = False
    ocr_languages: str = Field(default="eng", min_length=2, max_length=100, pattern=r"^[A-Za-z0-9_+.-]+$")
    ocr_dpi: int = Field(default=150, ge=72, le=300)
    max_ocr_pages: int = Field(default=50, ge=1, le=500)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()