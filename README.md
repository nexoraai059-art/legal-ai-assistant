# Real-Time AI Legal Research & Compliance Assistant

AI-assisted legal research for document-grounded answers with citations, real-time case monitoring, compliance deadline detection, and live notifications.

## Stack
- Frontend: React + Vite
- Backend: Python + FastAPI
- PDF extraction: PyMuPDF
- Local development metadata: SQLite
- Planned retrieval: embeddings + ChromaDB or Qdrant
- Planned RAG orchestration: LangChain + hosted LLM API
- Planned real-time: FastAPI SSE/WebSockets

## Current implementation
- FastAPI health endpoint and React workspace shell.
- PDF upload with extension, MIME, signature, size, page-count, and password-protection checks.
- Text extraction with page markers using PyMuPDF.
- UUID-based file storage, SHA-256 file hashes, SQLite metadata, list/detail/delete endpoints.
- React document library with upload, filename filtering, extracted-text preview, and delete.
- Backend tests for health, upload/extraction/list/detail/delete, and invalid uploads.

Not implemented yet: authentication/authorization, semantic retrieval, RAG chat, streaming, case tracking, reminders, notifications, and deployment hardening.

## Windows development setup
Open two terminals from the repository root.

### 1. Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs
Health check: http://127.0.0.1:8000/health

### 2. Frontend
```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

Open the URL printed by Vite, usually http://localhost:5173.

### 3. Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

## Document API
- `POST /api/documents` — multipart upload; form field `file`.
- `GET /api/documents` — list document metadata.
- `GET /api/documents/{id}` — document metadata and extracted text.
- `DELETE /api/documents/{id}` — delete stored file and metadata.

Defaults: 15 MB maximum upload and 500 pages per PDF. Change `MAX_UPLOAD_MB` and `MAX_PDF_PAGES` in the backend environment.

## Local data and privacy
By default, PDFs and the SQLite database are stored under `backend/data/`, which is ignored by Git. Stored files use generated UUID filenames, not user-provided paths. Keep this folder backed up if local persistence matters. No OCR is performed on scanned/image-only PDFs yet.

**Security limitation:** document endpoints currently have no login or case-level authorization. This is a local development milestone only. Do not expose the API publicly or upload confidential client files until authentication, authorization, and production storage protections are implemented.

## Legal reliability
AI features are planned and must cite source passages. Do not invent authorities, quotations, or deadlines. Treat generated content as research assistance rather than legal advice, and independently verify all legal sources and dates.

## Dataset samples
Benchmark samples are stored under `datasets/generated/`. Review each dataset's licence and terms before training, redistribution, or production use. These benchmark samples are not a store for private case documents.