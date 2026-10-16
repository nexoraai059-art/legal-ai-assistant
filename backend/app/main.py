from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0", description="Real-time legal research and compliance assistant API.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "legal-ai-assistant"}


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Legal AI Assistant API", "docs": "/docs"}
