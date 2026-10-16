"""OpenAI-compatible hosted embeddings client. API keys stay server-side."""

from typing import Any

import httpx

from app.core.config import settings


class EmbeddingConfigurationError(Exception):
    """Raised when the hosted embedding provider has not been configured."""


class EmbeddingProviderError(Exception):
    """Raised when the hosted embedding provider cannot return valid vectors."""


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not settings.embedding_api_key:
        raise EmbeddingConfigurationError(
            "Semantic search is not configured yet. Set EMBEDDING_API_KEY in backend/.env."
        )
    base_url = settings.embedding_api_base_url.rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            json={"model": settings.embedding_model, "input": texts},
            timeout=httpx.Timeout(45.0, connect=10.0),
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        items = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in items]
        if len(vectors) != len(texts) or any(not isinstance(v, list) or not v for v in vectors):
            raise EmbeddingProviderError("The embedding provider returned an unexpected response.")
        if any(any(not isinstance(n, (int, float)) for n in vector) for vector in vectors):
            raise EmbeddingProviderError("The embedding provider returned invalid vector values.")
        dimensions = len(vectors[0])
        if any(len(vector) != dimensions for vector in vectors):
            raise EmbeddingProviderError("The embedding provider returned inconsistent vector dimensions.")
        return [[float(number) for number in vector] for vector in vectors]
    except EmbeddingProviderError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise EmbeddingProviderError(
            "The embedding provider request failed. Check the endpoint, model, and API key."
        ) from exc