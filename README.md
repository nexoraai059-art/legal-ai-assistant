# Real-Time AI Legal Research & Compliance Assistant

A local-first workspace for managing legal documents, retrieving relevant passages, asking source-grounded questions, tracking cases, and generating in-app deadline notifications.

## Stack
- Frontend: React + Vite
- Backend: Python + FastAPI
- PDF extraction: PyMuPDF
- Metadata and case tracking: SQLite
- Vector retrieval: ChromaDB with cosine similarity
- Embeddings: OpenAI-compatible hosted embeddings API (default `text-embedding-3-small`)
- RAG orchestration: LangChain + OpenAI-compatible chat model
- Streaming: Server-Sent Events (SSE)

## Implemented
- One-time first-admin bootstrap, login, expiring bearer tokens, PBKDF2 password hashing, role-based write permissions, admin user management, and account disabling.
- Per-account isolation for documents, semantic retrieval, cases, deadlines, notifications, activity history, and dashboard metrics.
- API security headers, no-store caching for API responses, and per-IP failed-login throttling (10 attempts per 15 minutes by default).
- PDF upload validation, extraction, local file storage, SHA-256 hashes, metadata, listing, preview, and deletion.
- Page-aware overlapping chunks, hosted embeddings, persistent ChromaDB indexing, and semantic search.
- Document-grounded RAG chat that provides source labels and document/page metadata; unknown source labels are removed.
- SSE chat response streaming with source, token, completion, and error events.
- Case register, case status, user-confirmed deadlines, source document/page association, deadline completion, and activity logs.
- Background deadline checks every five minutes and deduplicated in-app upcoming/overdue notifications.
- React dashboard with summary metrics, case forms, deadline management, notifications, document library, semantic search, and RAG chat.
- Automated tests for document lifecycle, retrieval, chat citations, SSE, and deadline reminders.

## Still outstanding
- Per-case sharing/invitations and organization tenancy; records are isolated by account, but users cannot securely share a case with collaborators.
- Password reset, MFA, refresh-token revocation, and production audit identity.
- OCR for scanned PDFs, email/SMS/push notifications, and calendar integrations.
- Real-time notification push to connected browsers (current deadline notifications are persisted in-app; chat streams over SSE).
- Automated hosted-provider evaluation, full security review, deployment, and production backup/restore.

## Windows development setup
Open two terminals from the repository root.

### 1. Backend
```powershell
cd backend
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Copy the generated random value into `JWT_SECRET_KEY` in `backend/.env`. Also set `EMBEDDING_API_KEY`, `LLM_API_KEY`, and `LLM_MODEL`. Login throttling defaults to 10 failed attempts per 15 minutes; adjust `LOGIN_RATE_LIMIT_ATTEMPTS` and `LOGIN_RATE_LIMIT_WINDOW_MINUTES` if needed. Keep real keys out of Git. Then run:
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
- `GET /api/auth/bootstrap/status`, `POST /api/auth/bootstrap` — one-time first-admin setup.
- `POST /api/auth/login`, `GET /api/auth/me` — sign in and current account.
- `GET /api/auth/users`, `POST /api/auth/users`, `PATCH /api/auth/users/{id}/active` — admin account management.
- `POST /api/documents` — multipart PDF upload; form field `file`.
- `GET /api/documents` and `GET /api/documents/{id}` — document metadata and extracted text.
- `POST /api/documents/{id}/index` — chunk, embed, and index a document.
- `POST /api/search` — semantic search; JSON body `{"query":"...","limit":5}`.
- `POST /api/chat` — grounded answer with source metadata.
- `POST /api/chat/stream` — streamed RAG answer using SSE.
- `DELETE /api/documents/{id}` — remove the stored PDF, metadata, and vector chunks.
- `POST /api/cases`, `GET /api/cases`, `GET /api/cases/{id}`, `PATCH /api/cases/{id}` — case management.
- `POST /api/deadlines`, `GET /api/deadlines`, `PATCH /api/deadlines/{id}` — deadline management.
- `GET /api/notifications`, `POST /api/notifications/{id}/read` — in-app notifications.
- `POST /api/reminders/run` — run a reminder check immediately.
- `GET /api/activity` — recent activity log.
- `GET /api/dashboard/summary` — case/document/deadline summary counts.

Defaults: 15 MB maximum upload and 500 pages per PDF. Change `MAX_UPLOAD_MB` and `MAX_PDF_PAGES` in the backend environment.

## Local data and privacy
By default, PDFs, SQLite metadata, and the ChromaDB index are stored under `backend/data/`, which is ignored by Git. Stored files use generated UUID filenames, not user-provided paths. Keep this folder backed up if local persistence matters. Scanned/image-only PDFs currently need OCR, which is not yet implemented.

**Security limitation:** each account is isolated from other accounts' documents, search results, cases, deadlines, notifications, activity, and dashboard data. Controlled case sharing and organization tenancy are not implemented. This remains a local-development prototype; do not expose the API publicly or upload confidential client files until sharing controls and production hardening are complete. Hosted embeddings and chat send extracted passages to the configured provider; review provider privacy and data-processing terms before confidential use. Do not commit `.env` files or API keys.

## Deadline reliability
The application never automatically invents or saves legal deadlines. A person must confirm the date before it can be stored. Optional source document and page references are validated against uploaded documents. Reminder generation is based only on the stored, confirmed date; independently verify all legal dates and required actions.

## Legal reliability
The chat is instructed to answer only from retrieved excerpts, cite source labels, and acknowledge missing evidence. This is not a guarantee that every generated claim is correct: verify each cited passage in context and independently confirm legal authorities and deadlines. Treat the application as research assistance, not legal advice.

## Dataset samples
Benchmark samples are stored under `datasets/generated/`. Review each dataset's licence and terms before training, redistribution, or production use. These benchmark samples are not a store for private case documents.