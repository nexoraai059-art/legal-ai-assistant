"""Case tracking, user-confirmed deadlines, notifications, and activity history."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services import documents as document_store


DB_PATH = settings.data_dir / "legal_ai.sqlite3"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(connection: sqlite3.Connection, owner_id: str, action: str, entity_type: str,
         entity_id: str, description: str) -> None:
    connection.execute(
        "INSERT INTO activity_logs (id, actor, owner_id, action, entity_type, entity_id, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid4()), owner_id, owner_id, action, entity_type, entity_id, description, _now()),
    )


def initialize_case_storage() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                case_number TEXT,
                jurisdiction TEXT,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','closed','archived')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                owner_id TEXT NOT NULL DEFAULT 'legacy'
            );
            CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
            CREATE TABLE IF NOT EXISTS deadlines (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                source_document_id TEXT,
                source_page INTEGER,
                notes TEXT NOT NULL DEFAULT '',
                remind_days_before INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','cancelled')),
                user_confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_deadlines_due_date ON deadlines(due_date, status);
            CREATE INDEX IF NOT EXISTS idx_deadlines_case_id ON deadlines(case_id);
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                dedupe_key TEXT NOT NULL UNIQUE,
                notification_type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                case_id TEXT REFERENCES cases(id) ON DELETE SET NULL,
                deadline_id TEXT REFERENCES deadlines(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                read_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);
            CREATE TABLE IF NOT EXISTS activity_logs (
                id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                owner_id TEXT NOT NULL DEFAULT 'legacy'
            );
            CREATE INDEX IF NOT EXISTS idx_activity_created_at ON activity_logs(created_at DESC);
            """
        )
        for table in ("cases", "activity_logs"):
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "owner_id" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'legacy'")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "users" in tables:
            admin = connection.execute("SELECT id FROM users WHERE role='admin' ORDER BY created_at LIMIT 1").fetchone()
            if admin:
                for table in ("cases", "activity_logs"):
                    connection.execute(f"UPDATE {table} SET owner_id = ? WHERE owner_id = 'legacy'", (admin["id"],))
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cases_owner_id ON cases(owner_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_owner_id ON activity_logs(owner_id)")


def create_case(data: dict[str, Any], owner_id: str) -> dict[str, Any]:
    case_id = str(uuid4())
    now = _now()
    with _connect() as connection:
        connection.execute(
            """INSERT INTO cases (id, title, case_number, jurisdiction, description, status, created_at, updated_at, owner_id)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
            (case_id, data["title"].strip(), data.get("case_number"), data.get("jurisdiction"),
             data.get("description", ""), now, now, owner_id),
        )
        _log(connection, owner_id, "created", "case", case_id, f"Created case: {data['title'].strip()}")
    return get_case(case_id, owner_id)  # type: ignore[return-value]


def list_cases(owner_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT c.*, COUNT(DISTINCT d.id) AS deadline_count,
                      SUM(CASE WHEN d.status = 'pending' THEN 1 ELSE 0 END) AS pending_deadline_count
               FROM cases c LEFT JOIN deadlines d ON d.case_id = c.id
               WHERE c.owner_id = ?
               GROUP BY c.id ORDER BY c.updated_at DESC""",
            (owner_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_case(case_id: str, owner_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM cases WHERE id = ? AND owner_id = ?", (case_id, owner_id)).fetchone()
    return dict(row) if row else None


def update_case_status(case_id: str, status: str, owner_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT title FROM cases WHERE id = ? AND owner_id = ?", (case_id, owner_id)).fetchone()
        if row is None:
            return None
        connection.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ? AND owner_id = ?", (status, _now(), case_id, owner_id))
        _log(connection, owner_id, "status_changed", "case", case_id, f"Case status changed to {status}: {row['title']}")
    return get_case(case_id, owner_id)


def create_deadline(data: dict[str, Any], owner_id: str) -> dict[str, Any]:
    case_id = data["case_id"]
    if get_case(case_id, owner_id) is None:
        raise ValueError("The selected case does not exist.")
    document_id = data.get("source_document_id")
    source_page = data.get("source_page")
    if bool(document_id) != bool(source_page):
        raise ValueError("Provide both a source document and source page, or neither.")
    if document_id:
        document = document_store.get_document(document_id, owner_id)
        if document is None:
            raise ValueError("The source document does not exist.")
        if source_page < 1 or source_page > document["page_count"]:
            raise ValueError("The source page is outside the document's page range.")
    if not data.get("user_confirmed", False):
        raise ValueError("Confirm the deadline date before saving it.")

    deadline_id = str(uuid4())
    with _connect() as connection:
        connection.execute(
            """INSERT INTO deadlines
               (id, case_id, title, due_date, source_document_id, source_page, notes,
                remind_days_before, status, user_confirmed, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, NULL)""",
            (deadline_id, case_id, data["title"].strip(), data["due_date"].isoformat(),
             document_id, source_page, data.get("notes", ""),
             data.get("remind_days_before", 3), _now()),
        )
        _log(connection, owner_id, "created", "deadline", deadline_id,
             f"Created confirmed deadline '{data['title'].strip()}' due {data['due_date'].isoformat()}")
    return get_deadline(deadline_id, owner_id)  # type: ignore[return-value]


def list_deadlines(owner_id: str, case_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    query = """SELECT d.*, c.title AS case_title, c.case_number
               FROM deadlines d JOIN cases c ON c.id = d.case_id"""
    clauses: list[str] = ["c.owner_id = ?"]
    params: list[str] = [owner_id]
    if case_id:
        clauses.append("d.case_id = ?")
        params.append(case_id)
    if status:
        clauses.append("d.status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY d.due_date ASC, d.created_at DESC"
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_deadline(deadline_id: str, owner_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """SELECT d.*, c.title AS case_title, c.case_number
               FROM deadlines d JOIN cases c ON c.id = d.case_id WHERE d.id = ? AND c.owner_id = ?""",
            (deadline_id, owner_id),
        ).fetchone()
    return dict(row) if row else None


def update_deadline_status(deadline_id: str, status: str, owner_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT d.title FROM deadlines d JOIN cases c ON c.id = d.case_id WHERE d.id = ? AND c.owner_id = ?", (deadline_id, owner_id)).fetchone()
        if row is None:
            return None
        completed_at = _now() if status == "completed" else None
        connection.execute(
            "UPDATE deadlines SET status = ?, completed_at = ? WHERE id = ?",
            (status, completed_at, deadline_id),
        )
        _log(connection, owner_id, "status_changed", "deadline", deadline_id,
             f"Deadline status changed to {status}: {row['title']}")
    return get_deadline(deadline_id, owner_id)


def generate_reminder_notifications(today: date | None = None, owner_id: str | None = None) -> int:
    current_day = today or date.today()
    created = 0
    query = """SELECT d.id, d.case_id, d.title, d.due_date, d.remind_days_before, c.title AS case_title
               FROM deadlines d JOIN cases c ON c.id = d.case_id
               WHERE d.status = 'pending' AND c.status = 'active'"""
    params: tuple[str, ...] = ()
    if owner_id is not None:
        query += " AND c.owner_id = ?"
        params = (owner_id,)
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
        for row in rows:
            due_date = date.fromisoformat(row["due_date"])
            days_left = (due_date - current_day).days
            if days_left < 0:
                notification_type = "deadline_overdue"
                title = "Deadline overdue"
                body = f"{row['title']} for {row['case_title']} was due on {due_date.isoformat()}. Verify the source and required action."
            elif days_left <= row["remind_days_before"]:
                notification_type = "deadline_upcoming"
                title = "Upcoming deadline"
                body = f"{row['title']} for {row['case_title']} is due on {due_date.isoformat()} ({days_left} day(s) remaining)."
            else:
                continue
            dedupe_key = f"{row['id']}:{due_date.isoformat()}:{notification_type}"
            cursor = connection.execute(
                """INSERT OR IGNORE INTO notifications
                   (id, dedupe_key, notification_type, title, body, case_id, deadline_id, created_at, read_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (str(uuid4()), dedupe_key, notification_type, title, body,
                 row["case_id"], row["id"], _now()),
            )
            if cursor.rowcount:
                created += 1
    return created


def list_notifications(owner_id: str, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    query = """SELECT n.*, c.title AS case_title FROM notifications n
               JOIN cases c ON c.id = n.case_id WHERE c.owner_id = ?"""
    params: list[Any] = [owner_id]
    if unread_only:
        query += " AND n.read_at IS NULL"
    query += " ORDER BY n.created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def mark_notification_read(notification_id: str, owner_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        cursor = connection.execute(
            """UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL
               AND case_id IN (SELECT id FROM cases WHERE owner_id = ?)""",
            (_now(), notification_id, owner_id),
        )
        if cursor.rowcount:
            _log(connection, owner_id, "marked_read", "notification", notification_id, "Notification marked as read")
        row = connection.execute(
            """SELECT n.* FROM notifications n JOIN cases c ON c.id = n.case_id
               WHERE n.id = ? AND c.owner_id = ?""", (notification_id, owner_id)
        ).fetchone()
    return dict(row) if row else None


def list_activity(owner_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM activity_logs WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?", (owner_id, limit)
        ).fetchall()
    return [dict(row) for row in rows]


def dashboard_summary(owner_id: str) -> dict[str, int]:
    today = date.today()
    week_end = (today + timedelta(days=7)).isoformat()
    with _connect() as connection:
        cases_count = connection.execute("SELECT COUNT(*) FROM cases WHERE status = 'active' AND owner_id = ?", (owner_id,)).fetchone()[0]
        documents_count = connection.execute(
            """SELECT COUNT(DISTINCT d.id) FROM documents d
               LEFT JOIN document_shares s ON s.document_id = d.id AND s.user_id = ?
               WHERE d.owner_id = ? OR s.user_id = ?""", (owner_id, owner_id, owner_id)
        ).fetchone()[0]
        upcoming = connection.execute(
            """SELECT COUNT(*) FROM deadlines d JOIN cases c ON c.id = d.case_id
               WHERE c.owner_id = ? AND d.status = 'pending' AND d.due_date >= ? AND d.due_date <= ?""",
            (owner_id, today.isoformat(), week_end),
        ).fetchone()[0]
        overdue = connection.execute(
            """SELECT COUNT(*) FROM deadlines d JOIN cases c ON c.id = d.case_id
               WHERE c.owner_id = ? AND d.status = 'pending' AND d.due_date < ?""", (owner_id, today.isoformat())
        ).fetchone()[0]
        unread = connection.execute(
            """SELECT COUNT(*) FROM notifications n JOIN cases c ON c.id = n.case_id
               WHERE c.owner_id = ? AND n.read_at IS NULL""", (owner_id,)
        ).fetchone()[0]
    return {"active_cases": cases_count, "documents": documents_count,
            "upcoming_deadlines": upcoming, "overdue_deadlines": overdue, "unread_notifications": unread}