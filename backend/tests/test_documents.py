import io

import fitz
import pytest
from fastapi.testclient import TestClient

from app.core import config
from app import main
from app.services import documents as document_store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "private-data"
    upload_dir = data_dir / "documents"
    monkeypatch.setattr(config.settings, "data_dir", data_dir)
    monkeypatch.setattr(document_store, "DB_PATH", data_dir / "test.sqlite3")
    monkeypatch.setattr(document_store, "UPLOAD_DIR", upload_dir)
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