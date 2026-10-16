"""Encrypted, integrity-checked backups for local legal case data.

Stop the API process before creating or restoring a backup so the document files,
SQLite metadata, and Chroma index are captured as one consistent application state.
"""

import argparse
import base64
import binascii
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.config import settings


MAGIC = b"LAIBAK01"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024
DATABASE_SUFFIXES = {".sqlite3", ".sqlite", ".db"}


class BackupError(RuntimeError):
    """Raised when a backup cannot be created or safely restored."""


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _load_key(key_path: Path, *, create: bool) -> tuple[bytes, bool]:
    key_path = key_path.expanduser().resolve()
    if key_path.exists():
        try:
            key = base64.urlsafe_b64decode(key_path.read_bytes().strip())
        except (OSError, ValueError, binascii.Error) as exc:
            raise BackupError(f"Could not read the encryption key file: {key_path}") from exc
        if len(key) != 32:
            raise BackupError("The backup key file is invalid; a 32-byte AES-256 key is required.")
        return key, False
    if not create:
        raise BackupError(f"Encryption key not found: {key_path}")

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    encoded = base64.urlsafe_b64encode(key) + b"\n"
    try:
        descriptor = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _load_key(key_path, create=False)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
    except OSError as exc:
        try:
            key_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise BackupError(f"Could not write the encryption key file: {key_path}") from exc
    return key, True


def _sqlite_snapshot(source_path: Path, snapshot_path: Path) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    source = None
    destination = None
    try:
        source = sqlite3.connect(str(source_path), timeout=30)
        destination = sqlite3.connect(str(snapshot_path), timeout=30)
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(f"SQLite integrity check failed for {source_path.name}.")
    except sqlite3.Error as exc:
        raise BackupError(f"Could not create a consistent SQLite snapshot of {source_path}.") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()


def _backup_file_sources(data_dir: Path, snapshot_root: Path) -> list[tuple[Path, str]]:
    if not data_dir.is_dir():
        raise BackupError(f"Data directory does not exist: {data_dir}")
    if not (data_dir / "legal_ai.sqlite3").is_file():
        raise BackupError(f"No legal_ai.sqlite3 database was found in {data_dir}.")

    sources: list[tuple[Path, str]] = []
    database_paths: set[str] = set()
    for path in data_dir.rglob("*"):
        if path.is_symlink():
            raise BackupError(f"Symbolic links are not allowed in the data directory: {path}")
        if not path.is_file() or path.suffix.lower() not in DATABASE_SUFFIXES:
            continue
        relative = path.relative_to(data_dir).as_posix()
        snapshot = snapshot_root.joinpath(*PurePosixPath(relative).parts)
        _sqlite_snapshot(path, snapshot)
        sources.append((snapshot, relative))
        database_paths.add(relative)

    for path in data_dir.rglob("*"):
        if path.is_symlink():
            raise BackupError(f"Symbolic links are not allowed in the data directory: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(data_dir).as_posix()
        if relative in database_paths or relative == "manifest.json":
            continue
        if relative.endswith(("-wal", "-shm")):
            continue
        sources.append((path, relative))

    if not any(relative == "legal_ai.sqlite3" for _, relative in sources):
        raise BackupError("The main SQLite database could not be included in the backup.")
    return sorted(sources, key=lambda item: item[1])


def _add_file_to_zip(archive: zipfile.ZipFile, source_path: Path, relative_path: str) -> dict[str, Any]:
    info = zipfile.ZipInfo(relative_path)
    info.compress_type = zipfile.ZIP_DEFLATED
    digest = hashlib.sha256()
    size_bytes = 0
    with source_path.open("rb") as source, archive.open(info, "w") as destination:
        while True:
            chunk = source.read(CHUNK_BYTES)
            if not chunk:
                break
            destination.write(chunk)
            digest.update(chunk)
            size_bytes += len(chunk)
    return {"path": relative_path, "size_bytes": size_bytes, "sha256": digest.hexdigest()}


def _encrypt_file(source_path: Path, output_path: Path, key: bytes) -> None:
    nonce = secrets.token_bytes(NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=output_path.name + ".", suffix=".partial", dir=output_path.parent)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            with source_path.open("rb") as source:
                destination.write(MAGIC)
                destination.write(nonce)
                while True:
                    chunk = source.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    destination.write(encryptor.update(chunk))
                destination.write(encryptor.finalize())
                destination.write(encryptor.tag)
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _decrypt_file(backup_path: Path, archive_path: Path, key: bytes) -> None:
    try:
        file_size = backup_path.stat().st_size
        header_size = len(MAGIC) + NONCE_BYTES
        if file_size < header_size + TAG_BYTES:
            raise BackupError("The backup file is incomplete.")
        with backup_path.open("rb") as source:
            if source.read(len(MAGIC)) != MAGIC:
                raise BackupError("This file is not a supported encrypted Legal AI backup.")
            nonce = source.read(NONCE_BYTES)
            source.seek(-TAG_BYTES, os.SEEK_END)
            tag = source.read(TAG_BYTES)
            ciphertext_size = file_size - header_size - TAG_BYTES
            source.seek(header_size)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(MAGIC)
            with archive_path.open("wb") as destination:
                remaining = ciphertext_size
                while remaining:
                    chunk = source.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise BackupError("The backup file ended unexpectedly.")
                    destination.write(decryptor.update(chunk))
                    remaining -= len(chunk)
                destination.write(decryptor.finalize())
    except InvalidTag as exc:
        archive_path.unlink(missing_ok=True)
        raise BackupError("Backup authentication failed. The file may be damaged or the key may be wrong.") from exc
    except OSError as exc:
        archive_path.unlink(missing_ok=True)
        raise BackupError(f"Could not read the backup file: {backup_path}") from exc
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def create_backup(data_dir: Path, output_path: Path, key_path: Path) -> dict[str, Any]:
    data_dir = data_dir.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    key_path = key_path.expanduser().resolve()
    if _is_within(output_path, data_dir):
        raise BackupError("Store the backup outside the live data directory.")
    if _is_within(key_path, data_dir):
        raise BackupError("Store the encryption key outside the live data directory.")
    if _is_within(key_path, output_path.parent):
        raise BackupError("Store the encryption key separately from the backup files.")
    if output_path.exists():
        raise BackupError(f"Backup output already exists; choose another path: {output_path}")

    key, key_created = _load_key(key_path, create=True)
    with tempfile.TemporaryDirectory(prefix="legal-ai-backup-") as temporary:
        temporary_dir = Path(temporary)
        snapshot_root = temporary_dir / "snapshots"
        snapshot_root.mkdir()
        sources = _backup_file_sources(data_dir, snapshot_root)
        archive_path = temporary_dir / "archive.zip"
        manifest_files: list[dict[str, Any]] = []
        try:
            with zipfile.ZipFile(archive_path, "w", allowZip64=True, compresslevel=3) as archive:
                for source_path, relative_path in sources:
                    manifest_files.append(_add_file_to_zip(archive, source_path, relative_path))
                manifest = {
                    "format": "legal-ai-assistant-backup",
                    "version": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "files": manifest_files,
                }
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
            _encrypt_file(archive_path, output_path, key)
        except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
            output_path.unlink(missing_ok=True)
            raise BackupError("Backup creation failed before it could be completed.") from exc

    return {
        "output": str(output_path),
        "files": len(manifest_files),
        "bytes": output_path.stat().st_size,
        "key_created": key_created,
        "key_path": str(key_path),
    }


def _safe_archive_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or ":" in name:
        raise BackupError("The backup contains an unsafe file path.")
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise BackupError("The backup contains an unsafe file path.")
    relative = PurePosixPath(name)
    if relative.is_absolute():
        raise BackupError("The backup contains an unsafe file path.")
    return relative


def _extract_and_verify(archive_path: Path, stage_dir: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = [info.filename for info in archive.infolist()]
            if len(names) != len(set(names)):
                raise BackupError("The backup contains duplicate archive entries.")
            info_by_name: dict[str, zipfile.ZipInfo] = {}
            for info in archive.infolist():
                if info.is_dir():
                    raise BackupError("Directory entries are not supported in this backup format.")
                _safe_archive_path(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise BackupError("The backup contains a symbolic link.")
                info_by_name[info.filename] = info
            if "manifest.json" not in info_by_name or info_by_name["manifest.json"].file_size > 2 * 1024 * 1024:
                raise BackupError("The backup manifest is missing or too large.")
            if archive.testzip() is not None:
                raise BackupError("The backup archive failed its CRC integrity check.")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != "legal-ai-assistant-backup" or manifest.get("version") != 1:
                raise BackupError("The backup format version is not supported.")
            entries = manifest.get("files")
            if not isinstance(entries, list):
                raise BackupError("The backup manifest is invalid.")
            expected_names: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise BackupError("The backup manifest contains an invalid file entry.")
                name = str(entry.get("path", ""))
                _safe_archive_path(name)
                if name == "manifest.json" or name in expected_names:
                    raise BackupError("The backup manifest contains duplicate or reserved paths.")
                expected_names.add(name)
                info = info_by_name.get(name)
                if info is None or info.file_size != entry.get("size_bytes"):
                    raise BackupError(f"The backup is missing a file or its size does not match: {name}")
            if set(info_by_name) != expected_names | {"manifest.json"}:
                raise BackupError("The backup contains unlisted files.")

            stage_dir.mkdir(parents=True, exist_ok=True)
            for entry in entries:
                name = str(entry["path"])
                relative = _safe_archive_path(name)
                destination = stage_dir.joinpath(*relative.parts)
                if not _is_within(destination, stage_dir):
                    raise BackupError("The backup contains a path that escapes the restore directory.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size_bytes = 0
                with archive.open(info_by_name[name], "r") as source, destination.open("wb") as output:
                    while True:
                        chunk = source.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        size_bytes += len(chunk)
                if size_bytes != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]:
                    raise BackupError(f"File integrity verification failed: {name}")
            if not (stage_dir / "legal_ai.sqlite3").is_file():
                raise BackupError("The backup does not contain the main legal_ai.sqlite3 database.")
            return manifest
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise BackupError("The decrypted backup archive is invalid or incomplete.") from exc


def _check_sqlite_files(data_dir: Path) -> None:
    for path in data_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in DATABASE_SUFFIXES:
            continue
        connection = None
        try:
            connection = sqlite3.connect(str(path), timeout=30)
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError(f"SQLite integrity check failed after restore: {path.name}")
        except sqlite3.Error as exc:
            raise BackupError(f"Could not validate restored database: {path.name}") from exc
        finally:
            if connection is not None:
                connection.close()


def restore_backup(
    backup_path: Path,
    target_dir: Path,
    key_path: Path,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    backup_path = backup_path.expanduser().resolve()
    target_dir = target_dir.expanduser().resolve()
    key_path = key_path.expanduser().resolve()
    if not backup_path.is_file():
        raise BackupError(f"Backup file not found: {backup_path}")
    if _is_within(backup_path, target_dir):
        raise BackupError("Store the encrypted backup outside the restore target directory.")
    if _is_within(key_path, target_dir):
        raise BackupError("Store the encryption key outside the restore target directory.")
    if _is_within(key_path, backup_path.parent):
        raise BackupError("Store the encryption key separately from the backup files.")
    if target_dir.exists() and not replace:
        raise BackupError(f"Restore target already exists; pass --replace to preserve it and restore: {target_dir}")

    key, _ = _load_key(key_path, create=False)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    previous_dir: Path | None = None
    with tempfile.TemporaryDirectory(prefix=".legal-ai-restore-", dir=target_dir.parent) as temporary:
        temporary_dir = Path(temporary)
        archive_path = temporary_dir / "archive.zip"
        stage_dir = temporary_dir / "restored-data"
        _decrypt_file(backup_path, archive_path, key)
        manifest = _extract_and_verify(archive_path, stage_dir)
        _check_sqlite_files(stage_dir)

        if target_dir.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            previous_dir = target_dir.with_name(f"{target_dir.name}.pre-restore-{stamp}")
            if previous_dir.exists():
                previous_dir = target_dir.with_name(f"{target_dir.name}.pre-restore-{stamp}-{secrets.token_hex(3)}")
            try:
                os.replace(target_dir, previous_dir)
            except OSError as exc:
                raise BackupError("Could not preserve the existing data directory; restore was not applied.") from exc
        try:
            os.replace(stage_dir, target_dir)
        except OSError as exc:
            if previous_dir is not None and previous_dir.exists() and not target_dir.exists():
                os.replace(previous_dir, target_dir)
            raise BackupError("Could not activate restored data; the prior data directory was preserved.") from exc

    return {
        "target": str(target_dir),
        "files": len(manifest["files"]),
        "previous_data": str(previous_dir) if previous_dir else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and restore encrypted Legal AI Assistant backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_data_dir = settings.data_dir
    default_key_path = default_data_dir.parent / "backup-encryption.key"

    backup_parser = subparsers.add_parser("backup", help="Create an encrypted backup.")
    backup_parser.add_argument("--data-dir", type=Path, default=default_data_dir)
    backup_parser.add_argument("--output", type=Path, default=None)
    backup_parser.add_argument("--key-file", type=Path, default=default_key_path)

    restore_parser = subparsers.add_parser("restore", help="Verify and restore an encrypted backup.")
    restore_parser.add_argument("backup_file", type=Path)
    restore_parser.add_argument("--target-dir", type=Path, default=default_data_dir)
    restore_parser.add_argument("--key-file", type=Path, default=default_key_path)
    restore_parser.add_argument("--replace", action="store_true", help="Preserve the existing target and replace it with the restored data.")

    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            output_path = args.output
            if output_path is None:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                output_path = args.data_dir.parent / "backups" / f"legal-ai-backup-{stamp}.lai"
            result = create_backup(args.data_dir, output_path, args.key_file)
            print(f"Encrypted backup created: {result['output']}")
            print(f"Included files: {result['files']} | Size: {result['bytes']:,} bytes")
            if result["key_created"]:
                print(f"New encryption key created: {result['key_path']}")
                print("Store that key securely and separately. Without it, this backup cannot be restored.")
        else:
            result = restore_backup(args.backup_file, args.target_dir, args.key_file, replace=args.replace)
            print(f"Backup restored to: {result['target']}")
            print(f"Verified files: {result['files']}")
            if result["previous_data"]:
                print(f"Previous data preserved at: {result['previous_data']}")
        return 0
    except BackupError as exc:
        parser.exit(2, f"Backup error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
