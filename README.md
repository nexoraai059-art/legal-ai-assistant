# Real-Time AI Legal Research & Compliance Assistant

AI-assisted legal research for document-grounded answers with citations, real-time case monitoring, compliance deadline detection, and live notifications.

## Stack
- Frontend: React + Vite
- Backend: Python + FastAPI
- RAG orchestration: LangChain (planned)
- LLM: hosted LLM API (server-side secret)
- Embeddings: hosted embedding API or BGE-M3 in a cloud runtime
- Vector search: choose ChromaDB or Qdrant
- Real-time: FastAPI WebSockets + Redis Pub/Sub
- PDF extraction: PyMuPDF
- Compliance NER: spaCy
- Background reminders: Celery or RQ if needed
- Evaluation: RAGAS and latency benchmarks

## Current status
Phase 1 foundation only: project layout, environment template, FastAPI health endpoint, and React dashboard shell. Document ingestion, authentication, retrieval, streaming, monitoring, and reminders are not implemented yet.

## Cloud-first approach
Use a cloud development environment connected to this GitHub repository. Provision persistent document storage, an application database, a vector database, and Redis as hosted services where required. A hosted LLM API avoids downloading local LLM weights. A hosted embedding provider avoids downloading BGE-M3 weights.

## Security
- Never commit real API keys or credentials.
- Store secrets in the deployment platform's environment settings.
- Enforce user- and case-level authorization before retrieving document chunks.
- Treat AI answers as research assistance, not legal advice; verify citations and deadlines.

## Backend start
From the backend directory in a Python environment: install requirements, then run `uvicorn app.main:app --reload`. Health check: `/health`; API docs: `/docs`.

## Frontend start
From the frontend directory in a Node.js environment: run `npm install`, then `npm run dev`.

These commands have not been executed in this repository environment.
