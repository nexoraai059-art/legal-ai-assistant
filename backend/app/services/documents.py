"""Local document storage and SQLite metadata for the development deployment.

Uploaded files are named by UUID, never by the user-supplied filename. Each document
is owned by the account that uploaded it. The data folder is excluded from Git.
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
    connection.execute("PRAGMA foreign_keys = ON")
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
                created_at TEXT NOT NULL,
                owner_id TEXT NOT NULL DEFAULT 'legacy'
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")}
        if "owner_id" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'legacy'")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "users" in tables:
            admin = connection.execute("SELECT id FROM users WHERE role='admin' ORDER BY created_at LIMIT 1").fetchone()
            if admin:
                connection.execute("UPDATE documents SET owner_id = ? WHERE owner_id = 'legacy'", (admin["id"],))
        connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_owner_id ON documents(owner_id)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS document_shares (
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                permission TEXT NOT NULL CHECK(permission IN ('read', 'write')),
                granted_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (document_id, user_id)
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_document_shares_user ON document_shares(user_id)")


def insert_document(document: dict[str, Any]) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO documents
            (id, original_filename, stored_filename, content_type, size_bytes, sha256,
             page_count, extracted_text, created_at, owner_id)
            VALUES (:id, :original_filename, :stored_filename, :content_type, :size_bytes,
                    :sha256, :page_count, :extracted_text, :created_at, :owner_id)""",
            document,
        )


def list_documents(owner_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT d.id, d.original_filename, d.content_type, d.size_bytes, d.sha256,
                      d.page_count, length(d.extracted_text) AS extracted_characters, d.created_at,
                      CASE WHEN d.owner_id = ? THEN 'owner' ELSE s.permission END AS access_level
               FROM documents d
               LEFT JOIN document_shares s ON s.document_id = d.id AND s.user_id = ?
               WHERE d.owner_id = ? OR s.user_id = ?
               ORDER BY d.created_at DESC""",
            (owner_id, owner_id, owner_id, owner_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_document(document_id: str, owner_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """SELECT d.id, d.owner_id, d.original_filename, d.content_type, d.size_bytes, d.sha256,
                      d.page_count, d.extracted_text, d.created_at,
                      CASE WHEN d.owner_id = ? THEN 'owner' ELSE s.permission END AS access_level
               FROM documents d
               LEFT JOIN document_shares s ON s.document_id = d.id AND s.user_id = ?
               WHERE d.id = ? AND (d.owner_id = ? OR s.user_id = ?)""",
            (owner_id, owner_id, document_id, owner_id, owner_id),
        ).fetchone()
    return dict(row) if row else None


def list_document_shares(document_id: str, owner_id: str) -> list[dict[str, Any]] | None:
    with _connect() as connection:
        document = connection.execute(
            "SELECT 1 FROM documents WHERE id = ? AND owner_id = ?", (document_id, owner_id)
        ).fetchone()
        if document is None:
            return None
        rows = connection.execute(
            """SELECT s.user_id, u.full_name, u.email, s.permission, s.created_at
               FROM document_shares s JOIN users u ON u.id = s.user_id
               WHERE s.document_id = ? ORDER BY u.full_name COLLATE NOCASE""",
            (document_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def share_document(document_id: str, owner_id: str, email: str, permission: str) -> dict[str, Any]:
    if permission not in {"read", "write"}:
        raise ValueError("Permission must be read or write.")
    clean_email = email.strip().lower()
    if len(clean_email) > 254 or "@" not in clean_email:
        raise ValueError("Enter a valid account email address.")
    with _connect() as connection:
        document = connection.execute(
            "SELECT 1 FROM documents WHERE id = ? AND owner_id = ?", (document_id, owner_id)
        ).fetchone()
        if document is None:
            raise ValueError("Document not found or you are not its owner.")
        target = connection.execute(
            "SELECT id, full_name, email, role FROM users WHERE lower(email) = ? AND is_active = 1",
            (clean_email,),
        ).fetchone()
        if target is None:
            raise ValueError("No active account exists for that email address.")
        if target["id"] == owner_id:
            raise ValueError("The document owner already has full access.")
        if permission == "write" and target["role"] == "viewer":
            raise ValueError("Viewer accounts can only receive read access.")
        created_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """INSERT INTO document_shares (document_id, user_id, permission, granted_by, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(document_id, user_id) DO UPDATE SET
                 permission = excluded.permission, granted_by = excluded.granted_by,
                 created_at = excluded.created_at""",
            (document_id, target["id"], permission, owner_id, created_at),
        )
    return {
        "document_id": document_id,
        "user_id": target["id"],
        "full_name": target["full_name"],
        "email": target["email"],
        "permission": permission,
        "created_at": created_at,
    }


def revoke_document_share(document_id: str, owner_id: str, user_id: str) -> bool:
    with _connect() as connection:
        document = connection.execute(
            "SELECT 1 FROM documents WHERE id = ? AND owner_id = ?", (document_id, owner_id)
        ).fetchone()
        if document is None:
            return False
        cursor = connection.execute(
            "DELETE FROM document_shares WHERE document_id = ? AND user_id = ?",
            (document_id, user_id),
        )
    return cursor.rowcount > 0


def delete_document(document_id: str, owner_id: str) -> bool:
    with _connect() as connection:
        row = connection.execute("SELECT stored_filename FROM documents WHERE id = ? AND owner_id = ?", (document_id, owner_id)).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM documents WHERE id = ? AND owner_id = ?", (document_id, owner_id))
    (UPLOAD_DIR / row["stored_filename"]).unlink(missing_ok=True)
    return True


def document_owner_map() -> dict[str, str]:
    with _connect() as connection:
        rows = connection.execute("SELECT id, owner_id FROM documents").fetchall()
    return {row["id"]: row["owner_id"] for row in rows}


def build_document_record(*, document_id: str, owner_id: str, original_filename: str, stored_filename: str,
                          size_bytes: int, content: bytes, page_count: int,
                          extracted_text: str) -> dict[str, Any]:
    return {
        "id": document_id,
        "owner_id": owner_id,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "content_type": "application/pdf",
        "size_bytes": size_bytes,
        "sha256": hashlib.sha256(content).hexdigest(),
        "page_count": page_count,
        "extracted_text": extracted_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }