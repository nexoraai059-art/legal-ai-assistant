"""Persistent ChromaDB vector storage for legal-document chunks."""

from pathlib import Path
from typing import Any

import chromadb

from app.core.config import settings


CHROMA_DIR = settings.data_dir / "chroma"
COLLECTION_NAME = "legal_document_chunks"
_client: Any = None
_collection: Any = None


def initialize_vector_store() -> None:
    global _client, _collection
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _get_collection():
    if _collection is None:
        initialize_vector_store()
    return _collection


def replace_document_chunks(document_id: str, filename: str, chunks: list[dict[str, Any]],
                            embeddings: list[list[float]], model: str) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk must have exactly one embedding.")
    collection = _get_collection()
    ids = [f"{document_id}:{chunk['chunk_index']}" for chunk in chunks]
    if not chunks:
        collection.delete(where={"document_id": document_id})
        return
    # Embeddings are prepared before the previous index is removed.
    collection.delete(where={"document_id": document_id})
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=[chunk["text"] for chunk in chunks],
        metadatas=[{
            "document_id": document_id,
            "filename": filename,
            "page_start": int(chunk["page_start"]),
            "page_end": int(chunk["page_end"]),
            "chunk_index": int(chunk["chunk_index"]),
            "embedding_model": model,
        } for chunk in chunks],
    )


def search_chunks(query_embedding: list[float], limit: int = 5) -> list[dict[str, Any]]:
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(limit, count),
        include=["documents", "metadatas", "distances"],
    )
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    items: list[dict[str, Any]] = []
    for text, metadata, distance in zip(documents, metadatas, distances):
        items.append({
            "text": text,
            "document_id": metadata["document_id"],
            "filename": metadata["filename"],
            "page_start": metadata["page_start"],
            "page_end": metadata["page_end"],
            "chunk_index": metadata["chunk_index"],
            "score": round(1.0 - float(distance), 4),
        })
    return items


def remove_document_chunks(document_id: str) -> None:
    collection = _get_collection()
    collection.delete(where={"document_id": document_id})


def indexed_chunk_count() -> int:
    return int(_get_collection().count())


def document_is_indexed(document_id: str) -> bool:
    collection = _get_collection()
    found = collection.get(where={"document_id": document_id}, include=[])
    return bool(found.get("ids"))