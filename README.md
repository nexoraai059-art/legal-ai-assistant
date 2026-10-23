# Real-Time AI Legal Research & Compliance Assistant

A local-first workspace for managing legal documents, retrieving relevant passages, asking source-grounded questions, tracking cases, and generating in-app deadline notifications.

## Repository structure

The repository is organized into a React frontend, a FastAPI backend, local application data, public benchmark samples, and helper scripts.

```text
legal-ai-assistant/
|
|-- backend/                         # Python API and AI/document services
|   |-- app/
|   |   |-- main.py                  # FastAPI application and API routes
|   |   |-- core/
|   |   |   `-- config.py            # Environment-based configuration
|   |   `-- services/
|   |       |-- auth.py              # Login, sessions, roles, access checks
|   |       |-- cases.py             # Cases, deadlines, notifications, activity
|   |       |-- chat.py              # Retrieval-grounded AI chat and citations
|   |       |-- chunking.py          # Page-aware text chunking
|   |       |-- documents.py          # PDF metadata, storage, indexing workflow
|   |       |-- embeddings.py         # Embedding-provider client
|   |       |-- pdf_processing.py     # PDF text extraction and optional OCR
|   |       `-- vector_store.py       # Persistent ChromaDB retrieval
|   |
|   |-- data/                        # Local runtime data; intentionally not in Git
|   |   |-- documents/                # Uploaded PDFs with generated filenames
|   |   |-- chroma/                   # Persistent vector index
|   |   `-- legal_ai.sqlite3          # Local account/case/document metadata
|   |
|   |-- tests/                       # Automated backend tests
|   |   |-- test_backup.py
|   |   |-- test_chat.py
|   |   |-- test_documents.py
|   |   |-- test_embeddings.py
|   |   `-- test_pdf_processing.py
|   |
|   |-- .venv/                       # Local Python environment; do not commit
|   |-- .env                         # Private API keys/settings; do not commit
|   |-- .env.example                # Safe configuration template
|   `-- requirements.txt            # Python dependencies
|
|-- frontend/                       # React + Vite browser interface
|   |-- src/
|   |   |-- App.jsx                 # Main dashboard and user workflows
|   |   |-- main.jsx                # React entry point
|   |   `-- styles.css              # UI styling
|   |-- dist/                       # Generated build output; do not commit
|   |-- node_modules/                # Installed packages; do not commit
|   |-- index.html                  # Browser entry HTML
|   |-- package.json                # Scripts and frontend dependencies
|   |-- package-lock.json           # Reproducible npm dependency lockfile
|   `-- vite.config.js               # Vite development/build configuration
|
|-- datasets/                       # Small public legal benchmark samples
|   |-- generated/
|   |   |-- BillSum_legislative_bill_summarization.jsonl
|   |   |-- CUAD_Contract_Understanding_Atticus_Dataset.jsonl
|   |   |-- LegalBench-RAG.jsonl
|   |   |-- LexGLUE_CaseHOLD.jsonl
|   |   |-- LexGLUE_ECtHR_Article_Classification_A.jsonl
|   |   |-- LexGLUE_ECtHR_Article_Classification_B.jsonl
|   |   |-- LexGLUE_EURLEX.jsonl
|   |   |-- LexGLUE_LEDGAR.jsonl
|   |   |-- LexGLUE_SCOTUS.jsonl
|   |   `-- LexGLUE_Unfair_ToS.jsonl
|   |-- manifest.json               # Dataset identifiers/configuration notes
|   `-- README.md                   # Sample generation, workflow, license cautions
|
|-- scripts/
|   |-- download_legal_datasets.py  # Bounded benchmark-sample downloader
|   `-- live_monitor.ps1            # Local development/process monitor
|
|-- .github/workflows/              # CI and dataset workflow definitions
|-- .gitignore                      # Excludes secrets, local data and build files
`-- README.md                       # Main project guide (this file)
```

> **Important:** The tree documents the source layout. `backend/data/`, `.env` files, `.venv/`, `node_modules/`, and generated frontend build output are local runtime/configuration artifacts and should not be uploaded. The `datasets/generated/` directory contains benchmark samples, not private case files; review each upstream dataset's current license and terms before reuse.

### Folder and file guide

| Path | Purpose |
|---|---|
| `frontend/src/` | React screens for the dashboard, document library, search, chat, cases, deadlines, and notifications. |
| `backend/app/main.py` | Creates the FastAPI application and exposes the HTTP/SSE API. |
| `backend/app/services/auth.py` | Authentication, session handling, role checks, and account access controls. |
| `backend/app/services/pdf_processing.py` | Extracts selectable PDF text and optionally OCR-processes scanned pages when configured. |
| `backend/app/services/chunking.py` | Divides extracted text into overlapping chunks while retaining page context. |
| `backend/app/services/embeddings.py` | Requests vector embeddings from the configured compatible API provider. |
| `backend/app/services/vector_store.py` | Persists and retrieves vectors using ChromaDB. |
| `backend/app/services/chat.py` | Retrieves evidence for a question and creates a source-grounded answer. |
| `backend/app/services/cases.py` | Case records, user-confirmed deadlines, reminders, notifications, and activity. |
| `backend/data/` | Local documents, SQLite records, and vector index. Excluded from version control. |
| `backend/tests/` | Regression checks for document processing, retrieval/chat, embeddings, and backups. |
| `backend/.env.example` | Safe starting template; copy to `.env` and add your own secrets locally. |
| `datasets/` | Small benchmark/evaluation samples; these are not automatically used by runtime chat unless code explicitly loads them. |
| `scripts/` | Helper automation for dataset sample generation and local monitoring. |
| `.github/workflows/` | GitHub Actions automation, including tests/build and optional benchmark sample generation. |

### Request lifecycle: from PDF to cited answer

1. **Upload:** The React frontend sends a PDF to the FastAPI backend.
2. **Validate and extract:** The backend validates the file and extracts text with page information; optional OCR can handle scanned pages when enabled and installed.
3. **Chunk and embed:** Text is split into page-aware chunks, then sent to the configured embedding provider.
4. **Index:** Vectors and metadata are stored in ChromaDB; document metadata is maintained in SQLite.
5. **Ask:** A user's question is embedded and matched against permitted, indexed document passages.
6. **Generate:** The chat service passes retrieved evidence to the configured LLM and streams the response over Server-Sent Events (SSE).
7. **Verify:** The UI displays source labels/page metadata when available. Users must open and verify the underlying passage; generated answers are not guaranteed correct.

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
- One-time first-admin bootstrap, login/logout, expiring server-revocable bearer sessions, PBKDF2 password hashing, role-based write permissions, admin user management, and account disabling that revokes active sessions.
- Per-account isolation for documents, semantic retrieval, cases, deadlines, notifications, activity history, and dashboard metrics.
- Owner-managed case and document sharing by active account email, with read-only or write permissions, access-scoped deadlines/notifications, and immediate revocation.
- API security headers, no-store caching for API responses, and per-IP failed-login throttling (10 attempts per 15 minutes by default).
- PDF upload validation, selectable-text extraction, optional local OCR for scanned pages, local file storage, SHA-256 hashes, metadata, listing, preview, and deletion.
- Page-aware overlapping chunks, hosted embeddings, persistent ChromaDB indexing, and semantic search.
- Document-grounded RAG chat that provides source labels and document/page metadata; unknown source labels are removed.
- SSE chat response streaming with source, token, completion, and error events.
- Real-time notification SSE snapshots with reconnecting browser clients, per-account access filtering, and session revalidation while streams remain open.
- Case register, case status, user-confirmed deadlines, source document/page association, deadline completion, and activity logs.
- Background deadline checks every five minutes and deduplicated in-app upcoming/overdue notifications.
- Encrypted manual backup/restore for SQLite, uploaded PDFs, and Chroma data, with authenticated encryption, file-hash validation, SQLite integrity checks, and safe preservation of the previous data directory.
- React dashboard with summary metrics, case forms, deadline management, notifications, document library, semantic search, and RAG chat.
- Automated tests for document lifecycle, OCR fallback behavior, retrieval, chat citations, notification SSE, session revocation, deadline reminders, account isolation, case/document sharing, and encrypted backup/restore.

## Still outstanding
- Organization tenancy and cross-organization access policies; case and document sharing grants access to individual active accounts within the same local user store.
- Password reset, MFA, refresh-token revocation, and production audit identity.
- Email/SMS/push notifications and calendar integrations.
- WebSocket transport (chat and notification streaming currently use Server-Sent Events, SSE).
- Automated hosted-provider evaluation, full security review, deployment, and scheduled off-site backup/restore operations.

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
- `GET /api/auth/bootstrap/status`, `POST /api/auth/bootstrap` â€” one-time first-admin setup.
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` â€” sign in, revoke the current session, and inspect the current account.
- `GET /api/auth/users`, `POST /api/auth/users`, `PATCH /api/auth/users/{id}/active` â€” admin account management.
- `POST /api/documents` â€” multipart PDF upload; form field `file`.
- `GET /api/documents/{id}/shares`, `POST /api/documents/{id}/shares`, `DELETE /api/documents/{id}/shares/{user_id}` â€” owner-managed document sharing.
- `GET /api/documents` and `GET /api/documents/{id}` â€” document metadata and extracted text.
- `POST /api/documents/{id}/index` â€” chunk, embed, and index a document.
- `POST /api/search` â€” semantic search; JSON body `{"query":"...","limit":5}`.
- `POST /api/chat` â€” grounded answer with source metadata.
- `POST /api/chat/stream` â€” streamed RAG answer using SSE.
- `DELETE /api/documents/{id}` â€” remove the stored PDF, metadata, and vector chunks.
- `POST /api/cases`, `GET /api/cases`, `GET /api/cases/{id}`, `PATCH /api/cases/{id}` â€” case management.
- `GET/POST /api/cases/{id}/shares` and `DELETE /api/cases/{id}/shares/{user_id}` â€” owner-controlled case sharing.
- `POST /api/deadlines`, `GET /api/deadlines`, `PATCH /api/deadlines/{id}` â€” deadline management.
- `GET /api/notifications`, `GET /api/notifications/stream`, `POST /api/notifications/{id}/read` â€” in-app notifications and real-time SSE updates.
- `POST /api/reminders/run` â€” run a reminder check immediately.
- `GET /api/activity` â€” recent activity log.
- `GET /api/dashboard/summary` â€” case/document/deadline summary counts.

Defaults: 15 MB maximum upload and 500 pages per PDF. Change `MAX_UPLOAD_MB` and `MAX_PDF_PAGES` in the backend environment.

## Optional OCR for scanned PDFs

OCR is disabled by default. Install Tesseract OCR for Windows, make sure `tesseract.exe` is on `PATH`, then set these values in `backend/.env`:

```dotenv
OCR_ENABLED=true
OCR_LANGUAGES=eng
OCR_DPI=150
MAX_OCR_PAGES=50
```

Only pages with little or no selectable text are OCR-processed. The per-document OCR page limit prevents unexpectedly heavy CPU work; increase `MAX_OCR_PAGES` deliberately for longer scanned files. If Tesseract is unavailable, the upload returns a clear error instead of silently pretending OCR succeeded. OCR can misread legal names, case numbers, and dates, so verify recognized text against the page image before relying on it.

## Local data and privacy
By default, PDFs, SQLite metadata, and the ChromaDB index are stored under `backend/data/`, which is ignored by Git. Stored files use generated UUID filenames, not user-provided paths. Keep this folder backed up if local persistence matters. Optional OCR for scanned pages is supported when Tesseract is installed and `OCR_ENABLED=true`; it is disabled by default to avoid unexpected CPU-heavy processing.

**Security limitation:** each account is isolated from other accounts' documents, search results, cases, deadlines, notifications, activity, and dashboard data. Owners can share individual cases and documents with active accounts and revoke access; case and document sharing are not organization-level tenancy. Password reset, MFA, refresh-token revocation, external security review, and production deployment hardening are still outstanding. This remains a local-development prototype; do not expose the API publicly or upload confidential client files until production security review and operational safeguards are complete. Hosted embeddings and chat send extracted passages to the configured provider; review provider privacy and data-processing terms before confidential use. Do not commit `.env` files or API keys.

## Encrypted backup and restore

Stop the backend server before backing up or restoring data so the document files and Chroma index are not changing during the operation. From the repository root:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.backup backup
```

The encrypted `.lai` backup is written to `backend/backups/`. The first run creates `backend/backup-encryption.key`. **Keep that key in a secure location separate from the backup files**; anyone who obtains both can read the data, and losing the key makes the backup unrecoverable. The key and backup directory are excluded from Git.

To restore, stop the backend and use the exact backup filename:

```powershell
.\.venv\Scripts\python.exe -m app.backup restore .\backups\legal-ai-backup-YYYYMMDDTHHMMSSZ.lai --replace
```

`--replace` is required when the target data directory already exists. The tool verifies the backup before activating it and preserves the previous data directory as a timestamped sibling. Review that preserved directory before deleting it.

## Deadline reliability
The application never automatically invents or saves legal deadlines. A person must confirm the date before it can be stored. Optional source document and page references are validated against uploaded documents. Reminder generation is based only on the stored, confirmed date; independently verify all legal dates and required actions.

## Legal reliability
The chat is instructed to answer only from retrieved excerpts, cite source labels, and acknowledge missing evidence. This is not a guarantee that every generated claim is correct: verify each cited passage in context and independently confirm legal authorities and deadlines. Treat the application as research assistance, not legal advice.

## Dataset samples
Benchmark samples are stored under `datasets/generated/`. Review each dataset's licence and terms before training, redistribution, or production use. These benchmark samples are not a store for private case documents.

[executed on device: NIDHIN (47c41d4b-ef60-4c09-8668-4cc72e1eff30)]