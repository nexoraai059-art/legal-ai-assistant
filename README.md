# Real-Time AI Legal Research & Compliance Assistant

AI-assisted legal research for document-grounded answers with citations, real-time case monitoring, compliance deadline detection, and live notifications.

## Stack
- Frontend: React + Vite
- Backend: Python + FastAPI
- PDF extraction: PyMuPDF
- Metadata: SQLite
- Vector retrieval: ChromaDB with cosine similarity
- Embeddings: OpenAI-compatible hosted embeddings API (default model `text-embedding-3-small`)
- Planned RAG orchestration: LangChain + hosted LLM API
- Planned real-time: FastAPI SSE/WebSockets

## Current implementation
- FastAPI health endpoint and React workspace shell.
- PDF upload validation, text extraction, local file storage, SHA-256 hashes, SQLite metadata, list/detail/delete APIs.
- Page-aware text chunking with overlap and source page numbers.
- Hosted embedding provider integration and persistent ChromaDB indexing.
- Semantic search API and dashboard controls to index documents, search passages, and inspect page references.
- Backend tests for document lifecycle and text chunking.

Not implemented yet: authentication/authorization, cited LLM answers (RAG chat), streaming, case tracking, reminders, notifications, and deployment hardening.

## Windows development setup
Open two terminals from the repository root.

### 1. Backend
```powershell
cd backend
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```
Edit `backend/.env` and set `EMBEDDING_API_KEY` for semantic indexing and search. Keep real keys out of Git. Then run:
```powershell
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
.\\.venv\\Scripts\\python.exe -m pytest -q
```

## API endpoints
- `POST /api/documents` — multipart upload; form field `file`.
- `GET /api/documents` — list document metadata and index status.
- `GET /api/documents/{id}` — document metadata and extracted text.
- `POST /api/documents/{id}/index` — chunk, embed, and index a document.
- `POST /api/search` — semantic search; JSON body: `{"query":"...","limit":5}`.
- `DELETE /api/documents/{id}` — delete stored file, metadata, and vector chunks.

Defaults: 15 MB maximum upload and 500 pages per PDF. Change `MAX_UPLOAD_MB` and `MAX_PDF_PAGES` in the backend environment.

## Local data and privacy
By default, PDFs, SQLite metadata, and the ChromaDB index are stored under `backend/data/`, which is ignored by Git. Stored files use generated UUID filenames, not user-provided paths. Keep this folder backed up if local persistence matters. Scanned/image-only PDFs currently need OCR, which is not yet implemented.

**Security limitation:** document and search endpoints currently have no login or case-level authorization. This is a local development milestone only. Do not expose the API publicly or upload confidential client files until authentication, authorization, and production storage protections are implemented. When using hosted embeddings, extracted legal text is sent to the configured embedding provider; confirm the provider's privacy and data-processing terms before using confidential files.

## Legal reliability
Retrieval results show source document and page metadata; they are not legal conclusions. The planned chat must ground claims in source passages and must not invent authorities, quotations, or deadlines. Treat generated content as research assistance rather than legal advice, and independently verify all legal sources and dates.

## Dataset samples
Benchmark samples are stored under `datasets/generated/`. Review each dataset's licence and terms before training, redistribution, or production use. These benchmark samples are not a store for private case documents.