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
        metadata={"hnsw:space": "cosine", "owner_migration_version": 1},
    )
    metadata = dict(_collection.metadata or {})
    if metadata.get("owner_migration_version") != 1:
        _migrate_chunk_owners()
        metadata["owner_migration_version"] = 1
        _collection.modify(metadata=metadata)


def _get_collection():
    if _collection is None:
        initialize_vector_store()
    return _collection


def _migrate_chunk_owners() -> None:
    """Backfill ownership metadata for indexes created before account isolation."""
    from app.services import documents as document_store

    collection = _collection
    if collection is None or collection.count() == 0:
        return
    owners = document_store.document_owner_map()
    total = collection.count()
    for offset in range(0, total, 500):
        result = collection.get(limit=500, offset=offset, include=["metadatas"])
        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])
        update_ids: list[str] = []
        update_metadatas: list[dict[str, Any]] = []
        for chunk_id, metadata in zip(ids, metadatas):
            metadata = dict(metadata or {})
            owner_id = owners.get(metadata.get("document_id", ""), "legacy")
            if metadata.get("owner_id") != owner_id:
                metadata["owner_id"] = owner_id
                update_ids.append(chunk_id)
                update_metadatas.append(metadata)
        if update_ids:
            collection.update(ids=update_ids, metadatas=update_metadatas)


def reassign_owner(old_owner_id: str, new_owner_id: str) -> None:
    """Move legacy vector metadata when the first administrator claims old data."""
    collection = _get_collection()
    result = collection.get(where={"owner_id": old_owner_id}, include=["metadatas"])
    ids = result.get("ids", [])
    metadatas = [dict(item or {}, owner_id=new_owner_id) for item in result.get("metadatas", [])]
    if ids:
        collection.update(ids=ids, metadatas=metadatas)


def replace_document_chunks(document_id: str, owner_id: str, filename: str, chunks: list[dict[str, Any]],
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
            "owner_id": owner_id,
            "filename": filename,
            "page_start": int(chunk["page_start"]),
            "page_end": int(chunk["page_end"]),
            "chunk_index": int(chunk["chunk_index"]),
            "embedding_model": model,
        } for chunk in chunks],
    )


def search_chunks(query_embedding: list[float], limit: int = 5, owner_id: str | None = None,
                  document_ids: list[str] | None = None) -> list[dict[str, Any]]:
    collection = _get_collection()
    if document_ids is not None:
        if not document_ids:
            return []
        where = {"document_id": {"$in": document_ids}}
    else:
        where = {"owner_id": owner_id} if owner_id is not None else None
    if where:
        count = len(collection.get(where=where, include=[]).get("ids", []))
    else:
        count = collection.count()
    if count == 0:
        return []
    query_args: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": min(limit, count),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_args["where"] = where
    result = collection.query(**query_args)
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


def indexed_chunk_count(owner_id: str | None = None, document_ids: list[str] | None = None) -> int:
    collection = _get_collection()
    if document_ids is not None:
        if not document_ids:
            return 0
        return len(collection.get(where={"document_id": {"$in": document_ids}}, include=[]).get("ids", []))
    if owner_id is None:
        return int(collection.count())
    return len(collection.get(where={"owner_id": owner_id}, include=[]).get("ids", []))


def document_is_indexed(document_id: str, owner_id: str | None = None) -> bool:
    collection = _get_collection()
    where = {"document_id": document_id} if owner_id is None else {
        "$and": [{"document_id": document_id}, {"owner_id": owner_id}]
    }
    found = collection.get(where=where, include=[])
    return bool(found.get("ids"))