# Real-Time AI Legal Research & Compliance Assistant

AI-assisted legal research for document-grounded answers with citations, real-time case monitoring, compliance deadline detection, and live notifications.

## Stack
- Frontend: React + Vite
- Backend: Python + FastAPI
- PDF extraction: PyMuPDF
- Metadata: SQLite
- Vector retrieval: ChromaDB with cosine similarity
- Embeddings: OpenAI-compatible hosted embeddings API (default `text-embedding-3-small`)
- RAG orchestration: LangChain prompt + chat model integration
- Planned real-time: FastAPI SSE/WebSockets

## Current implementation
- FastAPI health endpoint and React workspace shell.
- PDF upload validation, text extraction, local file storage, SHA-256 hashes, SQLite metadata, list/detail/delete APIs.
- Page-aware text chunking with overlap and source page numbers.
- Hosted embedding provider integration and persistent ChromaDB indexing.
- Semantic search API and dashboard controls to index documents, search passages, and inspect page references.
- RAG chat that retrieves passages, instructs the model to answer only from supplied excerpts, labels sources as `[S1]`, `[S2]`, and returns document/page metadata.
- Automated backend tests for document lifecycle, chunking, indexing/search, and chat source metadata.

Not implemented yet: authentication/authorization, real-time token streaming, case tracking, reminders, notifications, and deployment hardening.

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
Edit `backend/.env` and set `EMBEDDING_API_KEY`, `LLM_API_KEY`, and `LLM_MODEL`. Keep real keys out of Git. Then run:
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
- `POST /api/chat` — RAG answer with source labels and document/page references; JSON body: `{"question":"...","limit":5}`.
- `DELETE /api/documents/{id}` — delete stored file, metadata, and vector chunks.

Defaults: 15 MB maximum upload and 500 pages per PDF. Change `MAX_UPLOAD_MB` and `MAX_PDF_PAGES` in the backend environment.

## Local data and privacy
By default, PDFs, SQLite metadata, and the ChromaDB index are stored under `backend/data/`, which is ignored by Git. Stored files use generated UUID filenames, not user-provided paths. Keep this folder backed up if local persistence matters. Scanned/image-only PDFs currently need OCR, which is not yet implemented.

**Security limitation:** document and chat endpoints currently have no login or case-level authorization. This is a local development milestone only. Do not expose the API publicly or upload confidential client files until authentication, authorization, and production storage protections are implemented. Hosted embeddings and chat send relevant extracted passages to the configured provider; review provider privacy and data-processing terms before confidential use.

## Legal reliability
The chat is instructed to answer only from retrieved excerpts, use source labels, and acknowledge missing evidence. This is not a guarantee that each generated claim is correct: verify every cited passage in context and independently confirm legal authorities and deadlines. Treat the application as research assistance, not legal advice.

## Dataset samples
Benchmark samples are stored under `datasets/generated/`. Review each dataset's licence and terms before training, redistribution, or production use. These benchmark samples are not a store for private case documents.