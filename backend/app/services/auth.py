"""Small dependency-light auth layer: PBKDF2 password hashes and HS256 access tokens."""

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings


DB_PATH = settings.data_dir / "legal_ai.sqlite3"
PBKDF2_ITERATIONS = 310_000
DEV_SIGNING_KEY = secrets.token_bytes(32)
logger = logging.getLogger(__name__)
ALLOWED_ROLES = {"admin", "lawyer", "assistant", "viewer"}


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_email(email: str) -> str:
    clean = email.strip().lower()
    if len(clean) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", clean):
        raise ValueError("Enter a valid email address.")
    return clean


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$" + str(PBKDF2_ITERATIONS) + "$" + salt.hex() + "$" + digest.hex()


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _signing_key() -> bytes:
    if settings.jwt_secret_key:
        key = settings.jwt_secret_key.encode("utf-8")
        if len(key) < 32:
            raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes.")
        return key
    if settings.app_env.lower() == "production":
        raise RuntimeError("JWT_SECRET_KEY must be set in production.")
    return DEV_SIGNING_KEY


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def initialize_auth_storage() -> None:
    _signing_key()  # Validate configured signing secrets before accepting requests.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','lawyer','assistant','viewer')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS login_failures (
                id TEXT PRIMARY KEY,
                ip_address TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_login_failures_ip_created ON login_failures(ip_address, created_at)")


def login_retry_after_seconds(ip_address: str) -> int:
    """Return seconds until the oldest in-window failure expires, or zero if allowed."""
    now = datetime.now(timezone.utc)
    window = max(1, int(settings.login_rate_limit_window_minutes))
    attempts = max(1, int(settings.login_rate_limit_attempts))
    cutoff = (now - timedelta(minutes=window)).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            """SELECT created_at FROM login_failures
               WHERE ip_address = ? AND created_at >= ? ORDER BY created_at ASC LIMIT ?""",
            (ip_address or "unknown", cutoff, attempts),
        ).fetchall()
    if len(rows) < attempts:
        return 0
    oldest = datetime.fromisoformat(rows[0]["created_at"])
    return max(1, int((oldest + timedelta(minutes=window) - now).total_seconds()))


def record_login_failure(ip_address: str) -> None:
    now = datetime.now(timezone.utc)
    with _connect() as connection:
        connection.execute("DELETE FROM login_failures WHERE created_at < ?", ((now - timedelta(days=1)).isoformat(),))
        connection.execute(
            "INSERT INTO login_failures (id, ip_address, created_at) VALUES (?, ?, ?)",
            (str(uuid4()), ip_address or "unknown", now.isoformat()),
        )


def clear_login_failures(ip_address: str) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM login_failures WHERE ip_address = ?", (ip_address or "unknown",))


def user_count() -> int:
    with _connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def _create_user_in_connection(connection: sqlite3.Connection, *, email: str, full_name: str,
                               password: str, role: str) -> dict[str, Any]:
    if role not in ALLOWED_ROLES:
        raise ValueError("Role must be admin, lawyer, assistant, or viewer.")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")
    clean_name = full_name.strip()
    if len(clean_name) < 2:
        raise ValueError("Full name must contain at least 2 non-space characters.")
    user_id = str(uuid4())
    connection.execute(
        """INSERT INTO users (id, email, full_name, password_hash, role, is_active, created_at, last_login_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, NULL)""",
        (user_id, _normalise_email(email), clean_name, _hash_password(password), role, _now()),
    )
    row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public_user(row)


def _claim_legacy_data(connection: sqlite3.Connection, owner_id: str) -> None:
    """Assign records created before login existed to the first administrator."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("documents", "cases", "activity_logs"):
        if table not in tables:
            continue
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if "owner_id" in columns:
            connection.execute(f"UPDATE {table} SET owner_id = ? WHERE owner_id = 'legacy'", (owner_id,))


def bootstrap_admin(*, email: str, full_name: str, password: str) -> dict[str, Any] | None:
    """Atomically create the first administrator only; subsequent calls are rejected."""
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return None
        user = _create_user_in_connection(
            connection, email=email, full_name=full_name, password=password, role="admin"
        )
        _claim_legacy_data(connection, user["id"])
    try:
        from app.services import vector_store
        vector_store.reassign_owner("legacy", user["id"])
    except Exception:
        logger.exception("Could not migrate legacy vector ownership; re-index existing documents")
    return user


def create_user(*, email: str, full_name: str, password: str, role: str) -> dict[str, Any]:
    try:
        with _connect() as connection:
            return _create_user_in_connection(
                connection, email=email, full_name=full_name, password=password, role=role
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with this email already exists.") from exc


def get_user_by_email(email: str) -> dict[str, Any] | None:
    try:
        clean_email = _normalise_email(email)
    except ValueError:
        return None
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE email = ?", (clean_email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public_user(row) if row else None


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    row = get_user_by_email(email)
    if not row or not row["is_active"] or not _verify_password(password, row["password_hash"]):
        return None
    with _connect() as connection:
        connection.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), row["id"]))
    return get_user_by_id(row["id"])


def set_user_active(user_id: str, is_active: bool) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        if row["role"] == "admin" and row["is_active"] and not is_active:
            active_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError("The last active administrator cannot be disabled.")
        connection.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
    return get_user_by_id(user_id)


def list_users() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, email, full_name, role, is_active, created_at, last_login_at FROM users ORDER BY created_at"
        ).fetchall()
    return [_public_user(row) for row in rows]


def create_access_token(user: dict[str, Any]) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user["id"],
        "role": user["role"],
        "iat": now,
        "exp": now + settings.access_token_minutes * 60,
        "jti": str(uuid4()),
    }
    unsigned = _b64encode(json.dumps(header, separators=(",", ":")).encode()) + "." + _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(_signing_key(), unsigned.encode("ascii"), hashlib.sha256).digest()
    return unsigned + "." + _b64encode(signature)


def user_from_token(token: str) -> dict[str, Any] | None:
    try:
        header_part, payload_part, signature_part = token.split(".")
        unsigned = header_part + "." + payload_part
        expected = _b64encode(hmac.new(_signing_key(), unsigned.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature_part):
            return None
        header = json.loads(_b64decode(header_part))
        payload = json.loads(_b64decode(payload_part))
        if header.get("alg") != "HS256" or payload.get("exp", 0) <= int(time.time()):
            return None
        user = get_user_by_id(str(payload.get("sub", "")))
        if not user or not user.get("is_active"):
            return None
        return user
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError):
        return None