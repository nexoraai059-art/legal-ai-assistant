"""Local document storage and SQLite metadata for the development deployment.

Uploaded files are named by UUID, never by the user-supplied filename. The data
folder is excluded from Git. Authentication and case-level authorization must be
added before exposing these routes to a shared or public deployment.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings


DB_PATH = settings.data_dir / "legal_ai.sqlite3"
UPLOAD_DIR = settings.data_dir / "documents"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_storage() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                extracted_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC)")


def insert_document(document: dict[str, Any]) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO documents
            (id, original_filename, stored_filename, content_type, size_bytes, sha256,
             page_count, extracted_text, created_at)
            VALUES (:id, :original_filename, :stored_filename, :content_type, :size_bytes,
                    :sha256, :page_count, :extracted_text, :created_at)""",
            document,
        )


def list_documents() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT id, original_filename, content_type, size_bytes, sha256,
                      page_count, length(extracted_text) AS extracted_characters, created_at
               FROM documents ORDER BY created_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def get_document(document_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """SELECT id, original_filename, content_type, size_bytes, sha256,
                      page_count, extracted_text, created_at
               FROM documents WHERE id = ?""",
            (document_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_document(document_id: str) -> bool:
    with _connect() as connection:
        row = connection.execute("SELECT stored_filename FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    (UPLOAD_DIR / row["stored_filename"]).unlink(missing_ok=True)
    return True


def build_document_record(*, document_id: str, original_filename: str, stored_filename: str,
                          size_bytes: int, content: bytes, page_count: int,
                          extracted_text: str) -> dict[str, Any]:
    return {
        "id": document_id,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "content_type": "application/pdf",
        "size_bytes": size_bytes,
        "sha256": hashlib.sha256(content).hexdigest(),
        "page_count": page_count,
        "extracted_text": extracted_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }