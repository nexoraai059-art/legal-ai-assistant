import io

import fitz
import pytest
from fastapi.testclient import TestClient

from app.core import config
from app import main
from app.services import documents as document_store
from app.services import vector_store
from app.services.chunking import chunk_document_text


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "private-data"
    upload_dir = data_dir / "documents"
    monkeypatch.setattr(config.settings, "data_dir", data_dir)
    monkeypatch.setattr(document_store, "DB_PATH", data_dir / "test.sqlite3")
    monkeypatch.setattr(document_store, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(vector_store, "CHROMA_DIR", data_dir / "chroma")
    monkeypatch.setattr(vector_store, "_client", None)
    monkeypatch.setattr(vector_store, "_collection", None)
    with TestClient(main.app) as test_client:
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
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit: [{
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
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit: [{
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
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit: [{
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
    monkeypatch.setattr(vector_store, "indexed_chunk_count", lambda: 1)
    monkeypatch.setattr(main.embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store, "search_chunks", lambda query_embedding, limit: [{
        "document_id": "doc-1", "filename": "notice.pdf", "page_start": 1,
        "page_end": 1, "chunk_index": 0, "score": 0.9, "text": "[Page 1] Notice terms.",
    }])
    monkeypatch.setattr(config.settings, "llm_api_key", "")
    monkeypatch.setattr(config.settings, "llm_model", "")
    response = client.post("/api/chat/stream", json={"question": "What are the notice terms?"})
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]