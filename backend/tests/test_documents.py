import asyncio
import io
from datetime import date, timedelta
from types import SimpleNamespace

import fitz
import pytest
from fastapi.testclient import TestClient

from app.core import config
from app import main
from app.services import auth as auth_service
from app.services import cases as case_service
from app.services import documents as document_store
from app.services import vector_store
from app.services.chunking import chunk_document_text


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "private-data"
    upload_dir = data_dir / "documents"
    monkeypatch.setattr(config.settings, "data_dir", data_dir)
    monkeypatch.setattr(document_store, "DB_PATH", data_dir / "test.sqlite3")
    monkeypatch.setattr(case_service, "DB_PATH", data_dir / "test.sqlite3")
    monkeypatch.setattr(auth_service, "DB_PATH", data_dir / "test.sqlite3")
    monkeypatch.setattr(document_store, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(vector_store, "CHROMA_DIR", data_dir / "chroma")
    monkeypatch.setattr(vector_store, "_client", None)
    monkeypatch.setattr(vector_store, "_collection", None)
    with TestClient(main.app) as test_client:
        bootstrap = test_client.post("/api/auth/bootstrap", json={
            "full_name": "Test Administrator",
            "email": "admin@example.test",
            "password": "StrongTestPassword123!",
        })
        assert bootstrap.status_code == 201, bootstrap.text
        login = test_client.post("/api/auth/login", data={
            "username": "admin@example.test",
            "password": "StrongTestPassword123!",
        })
        assert login.status_code == 200, login.text
        test_client.headers.update({"Authorization": "Bearer " + login.json()["access_token"]})
        yield test_client


def make_pdf(text: str = "This is a sample legal document.") -> bytes:
    stream = io.BytesIO()
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), text)
        pdf.save(stream)
    return stream.getvalue()


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_api_responses_are_not_cached(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_upload_extract_list_detail_and_delete(client):
    response = client.post(
        "/api/documents",
        files={"file": ("sample.pdf", make_pdf("Contract section 12: payment is due within 30 days."), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["page_count"] == 1
    assert created["text_extracted"] is True

    listing = client.get("/api/documents")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["items"][0]["id"] == created["id"]

    detail = client.get(f"/api/documents/{created['id']}")
    assert detail.status_code == 200
    assert "payment is due within 30 days" in detail.json()["extracted_text"]

    deleted = client.delete(f"/api/documents/{created['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/documents/{created['id']}").status_code == 404
    assert client.get("/api/documents").json()["count"] == 0


def test_rejects_non_pdf_extension(client):
    response = client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"not a PDF", "text/plain")},
    )
    assert response.status_code == 400


def test_rejects_fake_pdf_signature(client):
    response = client.post(
        "/api/documents",
        files={"file": ("fake.pdf", b"this is not a PDF", "application/pdf")},
    )
    assert response.status_code == 400

def test_chunker_preserves_page_numbers():
    chunks = chunk_document_text("[Page 1]\\nThe first page discusses notice.\\n\\n[Page 2]\\nThe second page discusses termination.")
    assert [chunk["page_start"] for chunk in chunks] == [1, 2]
    assert all(chunk["page_start"] == chunk["page_end"] for chunk in chunks)
    assert "termination" in chunks[1]["text"]


def test_index_search_and_delete_vector_chunks(client, monkeypatch):
    upload = client.post(
        "/api/documents",
        files={"file": ("terms.pdf", make_pdf("Termination requires thirty days of written notice."), "application/pdf")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["id"]

    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    indexed = client.post(f"/api/documents/{document_id}/index")
    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["chunks_indexed"] >= 1

    search = client.post("/api/search", json={"query": "termination notice", "limit": 5})
    assert search.status_code == 200, search.text
    assert search.json()["count"] >= 1
    assert search.json()["items"][0]["filename"] == "terms.pdf"
    assert search.json()["items"][0]["page_start"] == 1

    listing = client.get("/api/documents")
    assert listing.json()["items"][0]["indexed"] is True

    deleted = client.delete(f"/api/documents/{document_id}")
    assert deleted.status_code == 204
    assert vector_store.indexed_chunk_count() == 0


def test_index_reports_missing_embedding_configuration(client, monkeypatch):
    upload = client.post(
        "/api/documents",
        files={"file": ("terms.pdf", make_pdf("Payment terms appear in this agreement."), "application/pdf")},
    )
    document_id = upload.json()["id"]
    monkeypatch.setattr(config.settings, "embedding_api_key", "")
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: (_ for _ in ()).throw(
        main.embeddings.EmbeddingConfigurationError("Semantic search is not configured yet.")
    ))
    response = client.post(f"/api/documents/{document_id}/index")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]

def test_chat_returns_answer_with_document_page_sources(client, monkeypatch):
    upload = client.post(
        "/api/documents",
        files={"file": ("agreement.pdf", make_pdf("The supplier must provide thirty days written notice."), "application/pdf")},
    )
    document_id = upload.json()["id"]
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda owner_id=None, document_ids=None: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit, owner_id=None, document_ids=None: [{
        "document_id": document_id,
        "filename": "agreement.pdf",
        "page_start": 1,
        "page_end": 1,
        "chunk_index": 0,
        "score": 0.91,
        "text": "[Page 1] The supplier must provide thirty days written notice.",
    }])
    monkeypatch.setattr(main.chat_service, "generate_answer", lambda question, sources: "The supplier must provide thirty days written notice [S1].")

    response = client.post("/api/chat", json={"question": "What notice is required?"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "[S1]" in payload["answer"]
    assert payload["sources"][0]["filename"] == "agreement.pdf"
    assert payload["sources"][0]["page_start"] == 1
    assert payload["disclaimer"]


def test_chat_requires_llm_configuration(client, monkeypatch):
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda owner_id=None, document_ids=None: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit, owner_id=None, document_ids=None: [{
        "document_id": "doc-1", "filename": "agreement.pdf", "page_start": 1,
        "page_end": 1, "chunk_index": 0, "score": 0.8, "text": "[Page 1] notice terms",
    }])
    monkeypatch.setattr(config.settings, "llm_api_key", "")
    monkeypatch.setattr(config.settings, "llm_model", "")
    response = client.post("/api/chat", json={"question": "What are the notice terms?"})
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]


def test_chat_removes_unknown_source_labels():
    from app.services.chat import validate_source_references

    answer = "The document says notice is required [S1]. Another claim [S9]."
    validated = validate_source_references(answer, [{"source_id": "S1"}])
    assert "[S1]" in validated
    assert "[S9]" not in validated
    assert "[unverified source reference omitted]" in validated

def test_chat_stream_sends_sse_source_token_and_done_events(client, monkeypatch):
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda owner_id=None, document_ids=None: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit, owner_id=None, document_ids=None: [{
        "document_id": "doc-1", "filename": "notice.pdf", "page_start": 2,
        "page_end": 2, "chunk_index": 0, "score": 0.9, "text": "[Page 2] Written notice is required.",
    }])
    monkeypatch.setattr(main.chat_service, "ensure_chat_configured", lambda: None)
    monkeypatch.setattr(main.chat_service, "stream_answer", lambda question, sources: iter(["Notice is required ", "[S1]."]))

    response = client.post("/api/chat/stream", json={"question": "Is written notice required?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: sources" in response.text
    assert '"filename": "notice.pdf"' in response.text
    assert "event: token" in response.text
    assert "Notice is required " in response.text
    assert "event: done" in response.text


def test_chat_stream_rejects_missing_llm_configuration_before_streaming(client, monkeypatch):
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda owner_id=None, document_ids=None: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit, owner_id=None, document_ids=None: [{
        "document_id": "doc-1", "filename": "notice.pdf", "page_start": 1,
        "page_end": 1, "chunk_index": 0, "score": 0.9, "text": "[Page 1] Notice terms.",
    }])
    monkeypatch.setattr(config.settings, "llm_api_key", "")
    monkeypatch.setattr(config.settings, "llm_model", "")
    response = client.post("/api/chat/stream", json={"question": "What are the notice terms?"})
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]

def test_case_deadline_reminder_notification_lifecycle(client):
    case_response = client.post("/api/cases", json={
        "title": "Contract dispute",
        "case_number": "CIV-2026-101",
        "jurisdiction": "Kerala",
        "description": "Test case record.",
    })
    assert case_response.status_code == 201, case_response.text
    case_id = case_response.json()["id"]

    deadline_response = client.post("/api/deadlines", json={
        "case_id": case_id,
        "title": "File written response",
        "due_date": (date.today() + timedelta(days=2)).isoformat(),
        "remind_days_before": 3,
        "user_confirmed": True,
    })
    assert deadline_response.status_code == 201, deadline_response.text
    deadline_id = deadline_response.json()["id"]

    first_run = client.post("/api/reminders/run")
    assert first_run.status_code == 200
    assert first_run.json()["notifications_created"] == 1
    second_run = client.post("/api/reminders/run")
    assert second_run.json()["notifications_created"] == 0

    unread = client.get("/api/notifications?unread_only=true")
    assert unread.status_code == 200
    assert unread.json()["count"] == 1
    notification_id = unread.json()["items"][0]["id"]
    assert unread.json()["items"][0]["case_title"] == "Contract dispute"

    marked_read = client.post(f"/api/notifications/{notification_id}/read")
    assert marked_read.status_code == 200
    assert client.get("/api/notifications?unread_only=true").json()["count"] == 0

    completed = client.patch(f"/api/deadlines/{deadline_id}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert client.post("/api/reminders/run").json()["notifications_created"] == 0
    summary = client.get("/api/dashboard/summary").json()
    assert summary["active_cases"] == 1
    assert summary["upcoming_deadlines"] == 0
    assert summary["unread_notifications"] == 0


def test_deadline_requires_user_confirmation(client):
    case_id = client.post("/api/cases", json={"title": "Confirmed deadline case"}).json()["id"]
    response = client.post("/api/deadlines", json={
        "case_id": case_id,
        "title": "Unconfirmed due date",
        "due_date": (date.today() + timedelta(days=5)).isoformat(),
        "user_confirmed": False,
    })
    assert response.status_code == 422
    assert "Confirm the deadline date" in response.json()["detail"]


def test_deadline_source_page_must_exist(client):
    case_id = client.post("/api/cases", json={"title": "Source validation case"}).json()["id"]
    upload = client.post(
        "/api/documents",
        files={"file": ("one-page.pdf", make_pdf("A one page legal document."), "application/pdf")},
    )
    document_id = upload.json()["id"]
    response = client.post("/api/deadlines", json={
        "case_id": case_id,
        "title": "Source-backed filing date",
        "due_date": (date.today() + timedelta(days=5)).isoformat(),
        "source_document_id": document_id,
        "source_page": 2,
        "user_confirmed": True,
    })
    assert response.status_code == 422
    assert "outside the document's page range" in response.json()["detail"]


def test_auth_bootstrap_is_one_time_and_me_returns_safe_user(client):
    assert client.get("/api/auth/bootstrap/status").json()["needs_bootstrap"] is False
    second_bootstrap = client.post("/api/auth/bootstrap", json={
        "full_name": "Second Administrator",
        "email": "second-admin@example.test",
        "password": "AnotherStrongPassword123!",
    })
    assert second_bootstrap.status_code == 409

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.test"
    assert me.json()["role"] == "admin"
    assert "password_hash" not in me.json()


def test_protected_api_rejects_missing_token(client):
    response = client.get("/api/cases", headers={"Authorization": ""})
    assert response.status_code == 401


def test_short_jwt_secret_is_rejected(client, monkeypatch):
    monkeypatch.setattr(config.settings, "jwt_secret_key", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        auth_service.initialize_auth_storage()


def test_viewer_role_can_read_but_cannot_create_case(client):
    created = client.post("/api/auth/users", json={
        "full_name": "Read Only User",
        "email": "viewer@example.test",
        "password": "ViewerStrongPassword123!",
        "role": "viewer",
    })
    assert created.status_code == 201, created.text
    assert "password_hash" not in created.json()

    login = client.post("/api/auth/login", data={
        "username": "viewer@example.test",
        "password": "ViewerStrongPassword123!",
    })
    assert login.status_code == 200
    viewer_id = created.json()["id"]
    viewer_token = login.json()["access_token"]
    admin_authorization = client.headers["Authorization"]
    client.headers.update({"Authorization": "Bearer " + viewer_token})

    assert client.get("/api/cases").status_code == 200
    denied = client.post("/api/cases", json={"title": "Viewer must not create cases"})
    assert denied.status_code == 403
    assert client.get("/api/auth/users").status_code == 403

    client.headers.update({"Authorization": admin_authorization})
    disabled = client.patch("/api/auth/users/" + viewer_id + "/active", json={"is_active": False})
    assert disabled.status_code == 200
    client.headers.update({"Authorization": "Bearer " + viewer_token})
    assert client.get("/api/cases").status_code == 401
    client.headers.update({"Authorization": admin_authorization})


def test_admin_cannot_disable_the_only_active_admin(client):
    user = client.get("/api/auth/me").json()
    response = client.patch(f"/api/auth/users/{user['id']}/active", json={"is_active": False})
    assert response.status_code == 400

def test_users_only_access_their_own_case_and_document_data(client, monkeypatch):
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    admin_user = client.get("/api/auth/me").json()
    admin_id = admin_user["id"]
    admin_authorization = client.headers["Authorization"]

    admin_upload = client.post(
        "/api/documents",
        files={"file": ("admin-private.pdf", make_pdf("Admin-only contract notice."), "application/pdf")},
    )
    assert admin_upload.status_code == 201, admin_upload.text
    admin_document_id = admin_upload.json()["id"]
    assert client.post(f"/api/documents/{admin_document_id}/index").status_code == 200

    admin_case_response = client.post("/api/cases", json={"title": "Admin private case"})
    assert admin_case_response.status_code == 201, admin_case_response.text
    admin_case_id = admin_case_response.json()["id"]
    admin_deadline_response = client.post("/api/deadlines", json={
        "case_id": admin_case_id,
        "title": "Admin private filing",
        "due_date": (date.today() + timedelta(days=2)).isoformat(),
        "source_document_id": admin_document_id,
        "source_page": 1,
        "user_confirmed": True,
    })
    assert admin_deadline_response.status_code == 201, admin_deadline_response.text
    admin_deadline_id = admin_deadline_response.json()["id"]

    new_user = client.post("/api/auth/users", json={
        "full_name": "Private Case Lawyer",
        "email": "lawyer-private@example.test",
        "password": "PrivateLawyerPassword123!",
        "role": "lawyer",
    })
    assert new_user.status_code == 201, new_user.text
    lawyer_id = new_user.json()["id"]
    login = client.post("/api/auth/login", data={
        "username": "lawyer-private@example.test",
        "password": "PrivateLawyerPassword123!",
    })
    assert login.status_code == 200
    lawyer_authorization = "Bearer " + login.json()["access_token"]
    client.headers.update({"Authorization": lawyer_authorization})

    assert client.get("/api/documents").json()["count"] == 0
    assert client.get(f"/api/documents/{admin_document_id}").status_code == 404
    assert client.post(f"/api/documents/{admin_document_id}/index").status_code == 404
    assert client.delete(f"/api/documents/{admin_document_id}").status_code == 404
    assert client.get("/api/cases").json()["count"] == 0
    assert client.get(f"/api/cases/{admin_case_id}").status_code == 404
    assert client.patch(f"/api/cases/{admin_case_id}", json={"status": "closed"}).status_code == 404
    assert client.get("/api/deadlines").json()["count"] == 0
    assert client.get(f"/api/deadlines?case_id={admin_case_id}").json()["count"] == 0
    assert client.patch(f"/api/deadlines/{admin_deadline_id}", json={"status": "completed"}).status_code == 404
    assert client.post("/api/search", json={"query": "contract notice"}).json()["count"] == 0
    assert client.get("/api/dashboard/summary").json()["documents"] == 0
    assert client.get("/api/dashboard/summary").json()["active_cases"] == 0

    lawyer_upload = client.post(
        "/api/documents",
        files={"file": ("lawyer-private.pdf", make_pdf("Lawyer-only contract termination."), "application/pdf")},
    )
    assert lawyer_upload.status_code == 201, lawyer_upload.text
    lawyer_document_id = lawyer_upload.json()["id"]
    assert client.post(f"/api/documents/{lawyer_document_id}/index").status_code == 200
    lawyer_case_response = client.post("/api/cases", json={"title": "Lawyer private case"})
    assert lawyer_case_response.status_code == 201, lawyer_case_response.text
    lawyer_case_id = lawyer_case_response.json()["id"]
    lawyer_deadline_response = client.post("/api/deadlines", json={
        "case_id": lawyer_case_id,
        "title": "Lawyer private filing",
        "due_date": (date.today() + timedelta(days=2)).isoformat(),
        "source_document_id": lawyer_document_id,
        "source_page": 1,
        "user_confirmed": True,
    })
    assert lawyer_deadline_response.status_code == 201, lawyer_deadline_response.text

    client.headers.update({"Authorization": admin_authorization})
    reminder_run = client.post("/api/reminders/run")
    assert reminder_run.status_code == 200
    admin_notifications = client.get("/api/notifications").json()["items"]
    assert len(admin_notifications) == 1
    admin_notification_id = admin_notifications[0]["id"]
    # The background worker processes all accounts independently of the admin's scoped manual check.
    assert case_service.generate_reminder_notifications() == 1
    assert client.get("/api/documents").json()["count"] == 1
    assert client.get("/api/cases").json()["count"] == 1
    assert client.get("/api/deadlines").json()["count"] == 1
    assert client.get(f"/api/documents/{lawyer_document_id}").status_code == 404
    assert client.get(f"/api/cases/{lawyer_case_id}").status_code == 404
    assert client.get("/api/dashboard/summary").json()["documents"] == 1

    client.headers.update({"Authorization": lawyer_authorization})
    assert client.get("/api/documents").json()["items"][0]["id"] == lawyer_document_id
    assert client.get("/api/cases").json()["items"][0]["id"] == lawyer_case_id
    assert client.get("/api/deadlines").json()["items"][0]["case_id"] == lawyer_case_id
    lawyer_notifications = client.get("/api/notifications").json()["items"]
    assert len(lawyer_notifications) == 1
    assert client.post(f"/api/notifications/{admin_notification_id}/read").status_code == 404
    search = client.post("/api/search", json={"query": "contract termination"})
    assert search.status_code == 200
    assert [item["filename"] for item in search.json()["items"]] == ["lawyer-private.pdf"]
    activity = client.get("/api/activity").json()["items"]
    assert activity and all(item["owner_id"] == lawyer_id for item in activity)


def test_vector_store_backfills_legacy_chunk_ownership(client):
    upload = client.post(
        "/api/documents",
        files={"file": ("legacy-index.pdf", make_pdf("Legacy indexed passage."), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    owner_id = client.get("/api/auth/me").json()["id"]
    collection = vector_store._get_collection()
    legacy_chunk_id = document_id + ":legacy"
    collection.upsert(
        ids=[legacy_chunk_id],
        embeddings=[[1.0, 0.0]],
        documents=["Legacy indexed passage."],
        metadatas=[{
            "document_id": document_id,
            "filename": "legacy-index.pdf",
            "page_start": 1,
            "page_end": 1,
            "chunk_index": 0,
            "embedding_model": "old-model",
        }],
    )

    vector_store._migrate_chunk_owners()
    migrated = collection.get(where={"owner_id": owner_id}, include=["metadatas"])
    assert legacy_chunk_id in migrated["ids"]
    migrated_metadata = migrated["metadatas"][migrated["ids"].index(legacy_chunk_id)]
    assert migrated_metadata["owner_id"] == owner_id

def test_login_rate_limits_repeated_failed_attempts(client):
    for _ in range(config.settings.login_rate_limit_attempts):
        failed = client.post("/api/auth/login", data={
            "username": "missing-user@example.test",
            "password": "IncorrectPassword123!",
        })
        assert failed.status_code == 401

    blocked = client.post("/api/auth/login", data={
        "username": "admin@example.test",
        "password": "StrongTestPassword123!",
    })
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0

def test_document_sharing_permissions_search_and_revocation(client, monkeypatch):
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    owner_authorization = client.headers["Authorization"]
    upload = client.post(
        "/api/documents",
        files={"file": ("shared-contract.pdf", make_pdf("Private agreement termination clause."), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    assert client.post(f"/api/documents/{document_id}/index").status_code == 200

    viewer = client.post("/api/auth/users", json={
        "full_name": "Read Only Collaborator",
        "email": "read-share@example.test",
        "password": "ReadOnlyPassword123!",
        "role": "viewer",
    })
    assert viewer.status_code == 201, viewer.text
    viewer_id = viewer.json()["id"]
    share_read = client.post(f"/api/documents/{document_id}/shares", json={
        "email": "read-share@example.test",
        "permission": "read",
    })
    assert share_read.status_code == 201, share_read.text
    owner_shares = client.get(f"/api/documents/{document_id}/shares")
    assert owner_shares.status_code == 200
    assert owner_shares.json()["count"] == 1

    viewer_login = client.post("/api/auth/login", data={
        "username": "read-share@example.test",
        "password": "ReadOnlyPassword123!",
    })
    assert viewer_login.status_code == 200
    viewer_authorization = "Bearer " + viewer_login.json()["access_token"]
    client.headers.update({"Authorization": viewer_authorization})
    visible = client.get("/api/documents").json()
    assert visible["count"] == 1
    assert visible["items"][0]["access_level"] == "read"
    assert client.get(f"/api/documents/{document_id}").json()["access_level"] == "read"
    assert client.post(f"/api/documents/{document_id}/index").status_code == 403
    assert client.get(f"/api/documents/{document_id}/shares").status_code == 404
    assert client.post(f"/api/documents/{document_id}/shares", json={
        "email": "read-share@example.test",
        "permission": "read",
    }).status_code == 404
    search = client.post("/api/search", json={"query": "agreement termination"})
    assert search.status_code == 200
    assert [item["filename"] for item in search.json()["items"]] == ["shared-contract.pdf"]
    assert client.get("/api/dashboard/summary").json()["documents"] == 1

    client.headers.update({"Authorization": owner_authorization})
    assert client.post(f"/api/documents/{document_id}/shares", json={
        "email": "read-share@example.test",
        "permission": "write",
    }).status_code == 422

    lawyer = client.post("/api/auth/users", json={
        "full_name": "Write Collaborator",
        "email": "write-share@example.test",
        "password": "WriteAccessPassword123!",
        "role": "lawyer",
    })
    assert lawyer.status_code == 201, lawyer.text
    lawyer_id = lawyer.json()["id"]
    share_write = client.post(f"/api/documents/{document_id}/shares", json={
        "email": "write-share@example.test",
        "permission": "write",
    })
    assert share_write.status_code == 201, share_write.text

    lawyer_login = client.post("/api/auth/login", data={
        "username": "write-share@example.test",
        "password": "WriteAccessPassword123!",
    })
    assert lawyer_login.status_code == 200
    client.headers.update({"Authorization": "Bearer " + lawyer_login.json()["access_token"]})
    lawyer_docs = client.get("/api/documents").json()
    assert lawyer_docs["count"] == 1
    assert lawyer_docs["items"][0]["access_level"] == "write"
    assert client.post(f"/api/documents/{document_id}/index").status_code == 200

    client.headers.update({"Authorization": owner_authorization})
    assert client.delete(f"/api/documents/{document_id}/shares/{viewer_id}").status_code == 204
    assert client.delete(f"/api/documents/{document_id}/shares/{lawyer_id}").status_code == 204
    client.headers.update({"Authorization": viewer_authorization})
    assert client.get("/api/documents").json()["count"] == 0
    assert client.post("/api/search", json={"query": "agreement termination"}).json()["count"] == 0
    client.headers.update({"Authorization": "Bearer " + lawyer_login.json()["access_token"]})
    assert client.get("/api/documents").json()["count"] == 0


def test_case_sharing_scopes_cases_deadlines_and_notifications(client):
    owner_authorization = client.headers["Authorization"]
    case_response = client.post("/api/cases", json={"title": "Shared contract case"})
    assert case_response.status_code == 201, case_response.text
    case_id = case_response.json()["id"]
    deadline_response = client.post("/api/deadlines", json={
        "case_id": case_id,
        "title": "Review filing date",
        "due_date": (date.today() + timedelta(days=2)).isoformat(),
        "remind_days_before": 3,
        "user_confirmed": True,
    })
    assert deadline_response.status_code == 201, deadline_response.text
    deadline_id = deadline_response.json()["id"]

    collaborator = client.post("/api/auth/users", json={
        "full_name": "Case Collaborator",
        "email": "case-collaborator@example.test",
        "password": "CaseCollaboratorPassword123!",
        "role": "lawyer",
    })
    assert collaborator.status_code == 201, collaborator.text
    collaborator_id = collaborator.json()["id"]

    read_share = client.post(f"/api/cases/{case_id}/shares", json={
        "email": "case-collaborator@example.test",
        "permission": "read",
    })
    assert read_share.status_code == 201, read_share.text
    assert client.get(f"/api/cases/{case_id}/shares").json()["count"] == 1

    login = client.post("/api/auth/login", data={
        "username": "case-collaborator@example.test",
        "password": "CaseCollaboratorPassword123!",
    })
    assert login.status_code == 200
    collaborator_authorization = "Bearer " + login.json()["access_token"]
    client.headers.update({"Authorization": collaborator_authorization})

    shared_cases = client.get("/api/cases").json()
    assert shared_cases["count"] == 1
    assert shared_cases["items"][0]["id"] == case_id
    assert shared_cases["items"][0]["access_level"] == "read"
    assert "owner_id" not in shared_cases["items"][0]
    assert client.get(f"/api/cases/{case_id}").json()["access_level"] == "read"
    assert client.get(f"/api/cases/{case_id}/shares").status_code == 404
    assert client.get("/api/deadlines").json()["items"][0]["access_level"] == "read"
    assert client.patch(f"/api/cases/{case_id}", json={"status": "closed"}).status_code == 403
    assert client.patch(f"/api/deadlines/{deadline_id}", json={"status": "completed"}).status_code == 403
    denied_deadline = client.post("/api/deadlines", json={
        "case_id": case_id,
        "title": "Unauthorized shared deadline",
        "due_date": (date.today() + timedelta(days=4)).isoformat(),
        "user_confirmed": True,
    })
    assert denied_deadline.status_code == 403

    client.headers.update({"Authorization": owner_authorization})
    viewer = client.post("/api/auth/users", json={
        "full_name": "Case Viewer",
        "email": "case-viewer@example.test",
        "password": "CaseViewerPassword123!",
        "role": "viewer",
    })
    assert viewer.status_code == 201
    viewer_write = client.post(f"/api/cases/{case_id}/shares", json={
        "email": "case-viewer@example.test",
        "permission": "write",
    })
    assert viewer_write.status_code == 422

    write_share = client.post(f"/api/cases/{case_id}/shares", json={
        "email": "case-collaborator@example.test",
        "permission": "write",
    })
    assert write_share.status_code == 201, write_share.text
    assert case_service.generate_reminder_notifications() == 2

    client.headers.update({"Authorization": collaborator_authorization})
    assert client.get("/api/notifications").json()["count"] == 1
    changed_case = client.patch(f"/api/cases/{case_id}", json={"status": "closed"})
    assert changed_case.status_code == 200, changed_case.text
    changed_deadline = client.patch(f"/api/deadlines/{deadline_id}", json={"status": "completed"})
    assert changed_deadline.status_code == 200, changed_deadline.text

    client.headers.update({"Authorization": owner_authorization})
    revoked = client.delete(f"/api/cases/{case_id}/shares/{collaborator_id}")
    assert revoked.status_code == 204
    client.headers.update({"Authorization": collaborator_authorization})
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.get("/api/cases").json()["count"] == 0
    assert client.get("/api/deadlines").json()["count"] == 0
    assert client.get("/api/notifications").json()["count"] == 0



def test_notification_stream_emits_access_scoped_snapshot(client, monkeypatch):
    monkeypatch.setattr(main, "NOTIFICATION_STREAM_INTERVAL_SECONDS", 0)
    user = client.get("/api/auth/me").json()
    token = client.headers["Authorization"].removeprefix("Bearer ")
    disconnect_checks = 0

    async def disconnected():
        nonlocal disconnect_checks
        disconnect_checks += 1
        return disconnect_checks > 1

    request = SimpleNamespace(
        state=SimpleNamespace(user=user),
        headers={"Authorization": "Bearer " + token},
        is_disconnected=disconnected,
    )
    response = asyncio.run(main.stream_notifications(request))
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"

    async def collect_stream():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    stream = asyncio.run(collect_stream())
    assert "event: snapshot\n" in stream
    assert '"items":[]' in stream
    assert '"summary":' in stream
    assert client.get("/api/notifications/stream", headers={"Authorization": ""}).status_code == 401



def test_logout_revokes_the_current_bearer_session(client):
    token_header = client.headers["Authorization"]
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200, logout.text
    assert logout.json()["message"] == "Signed out successfully."
    assert client.get("/api/auth/me", headers={"Authorization": token_header}).status_code == 401


def test_disabling_then_reenabling_user_does_not_restore_old_session(client):
    created = client.post("/api/auth/users", json={
        "full_name": "Session Revocation User",
        "email": "session-revocation@example.test",
        "password": "SessionRevocationPassword123!",
        "role": "lawyer",
    })
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    login = client.post("/api/auth/login", data={
        "username": "session-revocation@example.test",
        "password": "SessionRevocationPassword123!",
    })
    assert login.status_code == 200
    old_token = "Bearer " + login.json()["access_token"]

    disabled = client.patch(f"/api/auth/users/{user_id}/active", json={"is_active": False})
    assert disabled.status_code == 200, disabled.text
    enabled = client.patch(f"/api/auth/users/{user_id}/active", json={"is_active": True})
    assert enabled.status_code == 200, enabled.text
    assert client.get("/api/auth/me", headers={"Authorization": old_token}).status_code == 401
