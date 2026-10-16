import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app import backup


def _create_test_data(data_dir: Path) -> None:
    (data_dir / "documents").mkdir(parents=True)
    (data_dir / "chroma").mkdir(parents=True)
    with sqlite3.connect(data_dir / "legal_ai.sqlite3") as connection:
        connection.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, title TEXT NOT NULL)")
        connection.execute("INSERT INTO cases VALUES ('case-1', 'Confidential test matter')")
    with sqlite3.connect(data_dir / "chroma" / "chroma.sqlite3") as connection:
        connection.execute("CREATE TABLE vector_metadata (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO vector_metadata VALUES ('chunk-1')")
    (data_dir / "documents" / "case-document.pdf").write_bytes(b"%PDF-1.4 confidential fixture bytes")


def test_encrypted_backup_round_trip_restores_files_and_sqlite(tmp_path):
    data_dir = tmp_path / "data"
    _create_test_data(data_dir)
    output = tmp_path / "backups" / "test-backup.lai"
    key_file = tmp_path / "backup-encryption.key"

    result = backup.create_backup(data_dir, output, key_file)

    assert result["files"] == 3
    assert result["key_created"] is True
    assert output.read_bytes().startswith(backup.MAGIC)
    assert b"Confidential test matter" not in output.read_bytes()
    assert key_file.exists()

    target = tmp_path / "restored-data"
    restored = backup.restore_backup(output, target, key_file)

    assert restored["target"] == str(target.resolve())
    assert restored["previous_data"] is None
    assert (target / "documents" / "case-document.pdf").read_bytes() == b"%PDF-1.4 confidential fixture bytes"
    with sqlite3.connect(target / "legal_ai.sqlite3") as connection:
        assert connection.execute("SELECT title FROM cases WHERE id='case-1'").fetchone()[0] == "Confidential test matter"
    with sqlite3.connect(target / "chroma" / "chroma.sqlite3") as connection:
        assert connection.execute("SELECT id FROM vector_metadata").fetchone()[0] == "chunk-1"


def test_restore_refuses_to_replace_existing_data_without_explicit_flag(tmp_path):
    data_dir = tmp_path / "data"
    _create_test_data(data_dir)
    output = tmp_path / "backups" / "test-backup.lai"
    key_file = tmp_path / "backup-encryption.key"
    backup.create_backup(data_dir, output, key_file)
    target = tmp_path / "existing-data"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep existing data", encoding="utf-8")

    with pytest.raises(backup.BackupError, match="--replace"):
        backup.restore_backup(output, target, key_file)

    assert sentinel.read_text(encoding="utf-8") == "keep existing data"


def test_tampered_encrypted_backup_is_rejected_without_creating_target(tmp_path):
    data_dir = tmp_path / "data"
    _create_test_data(data_dir)
    output = tmp_path / "backups" / "test-backup.lai"
    key_file = tmp_path / "backup-encryption.key"
    backup.create_backup(data_dir, output, key_file)

    tampered = tmp_path / "backups" / "tampered.lai"
    payload = bytearray(output.read_bytes())
    payload[len(backup.MAGIC) + backup.NONCE_BYTES + 4] ^= 0x40
    tampered.write_bytes(payload)
    target = tmp_path / "should-not-exist"

    with pytest.raises(backup.BackupError, match="authentication failed"):
        backup.restore_backup(tampered, target, key_file)

    assert not target.exists()



def test_restore_with_replace_preserves_previous_data_directory(tmp_path):
    data_dir = tmp_path / "data"
    _create_test_data(data_dir)
    output = tmp_path / "backups" / "test-backup.lai"
    key_file = tmp_path / "backup-encryption.key"
    backup.create_backup(data_dir, output, key_file)

    target = tmp_path / "existing-data"
    target.mkdir()
    (target / "local-note.txt").write_text("previous data", encoding="utf-8")

    result = backup.restore_backup(output, target, key_file, replace=True)

    previous = Path(result["previous_data"])
    assert (target / "documents" / "case-document.pdf").is_file()
    assert (previous / "local-note.txt").read_text(encoding="utf-8") == "previous data"



def test_restore_rejects_archive_path_traversal(tmp_path):
    key_file = tmp_path / "backup-encryption.key"
    key, _ = backup._load_key(key_file, create=True)
    plain_archive = tmp_path / "malicious.zip"
    encrypted_backup = tmp_path / "backups" / "malicious.lai"
    payload = b"outside the restore directory"
    manifest = {
        "format": "legal-ai-assistant-backup",
        "version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "files": [{
            "path": "../escaped.txt",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }],
    }
    with zipfile.ZipFile(plain_archive, "w") as archive:
        archive.writestr("../escaped.txt", payload)
        archive.writestr("manifest.json", json.dumps(manifest))
    backup._encrypt_file(plain_archive, encrypted_backup, key)
    target = tmp_path / "restored-data"

    with pytest.raises(backup.BackupError, match="unsafe file path"):
        backup.restore_backup(encrypted_backup, target, key_file)

    assert not (tmp_path / "escaped.txt").exists()
    assert not target.exists()
