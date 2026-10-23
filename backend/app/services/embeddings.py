"""OpenAI-compatible hosted embeddings client. API keys stay server-side."""

from typing import Any

import httpx

from app.core.config import settings


class EmbeddingConfigurationError(Exception):
    """Raised when the hosted embedding provider has not been configured."""


class EmbeddingProviderError(Exception):
    """Raised when the hosted embedding provider cannot return valid vectors."""


EMBEDDING_BATCH_SIZE = 32


def embed_texts(texts: list[str], input_type: str = "passage") -> list[list[float]]:
    """Embed text in bounded batches so larger PDFs do not exceed provider request limits."""
    if not texts:
        return []
    if not settings.embedding_api_key:
        raise EmbeddingConfigurationError(
            "Semantic search is not configured yet. Set EMBEDDING_API_KEY in backend/.env."
        )
    base_url = settings.embedding_api_base_url.rstrip("/")
    if settings.embedding_model == "nvidia/nemotron-3-embed-1b" and input_type not in {"passage", "query"}:
        raise EmbeddingConfigurationError("Embedding input_type must be 'passage' or 'query'.")

    all_vectors: list[list[float]] = []
    expected_dimensions: int | None = None
    try:
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start:start + EMBEDDING_BATCH_SIZE]
            request_payload: dict[str, Any] = {
                "model": settings.embedding_model,
                "input": batch,
                "encoding_format": "float",
                "truncate": "END",
            }
            # NVIDIA Nemotron-3-Embed requires distinct passage/query modes.
            if settings.embedding_model == "nvidia/nemotron-3-embed-1b":
                request_payload["input_type"] = input_type
            response = httpx.post(
                f"{base_url}/embeddings",
                headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
                json=request_payload,
                timeout=httpx.Timeout(45.0, connect=10.0),
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            items = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
            vectors = [item.get("embedding") for item in items]
            if len(vectors) != len(batch) or any(not isinstance(v, list) or not v for v in vectors):
                raise EmbeddingProviderError("The embedding provider returned an unexpected response.")
            if any(any(not isinstance(n, (int, float)) for n in vector) for vector in vectors):
                raise EmbeddingProviderError("The embedding provider returned invalid vector values.")
            dimensions = len(vectors[0])
            if any(len(vector) != dimensions for vector in vectors):
                raise EmbeddingProviderError("The embedding provider returned inconsistent vector dimensions.")
            if expected_dimensions is not None and dimensions != expected_dimensions:
                raise EmbeddingProviderError("The embedding provider returned inconsistent vector dimensions.")
            expected_dimensions = dimensions
            all_vectors.extend([[float(number) for number in vector] for vector in vectors])
        return all_vectors
    except EmbeddingProviderError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise EmbeddingProviderError(
            "The embedding provider request failed. Check the endpoint, model, and API key."
        ) from exc

[executed on device: NIDHIN (47c41d4b-ef60-4c09-8668-4cc72e1eff30)]