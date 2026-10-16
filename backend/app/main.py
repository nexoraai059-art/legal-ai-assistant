from contextlib import asynccontextmanager
import asyncio
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from typing import Literal

from app.core.config import settings
from app.services import documents as document_store
from app.services import auth as auth_service
from app.services import cases as case_service
from app.services import chat as chat_service
from app.services import embeddings, vector_store
from app.services.chunking import chunk_document_text


logger = logging.getLogger(__name__)
NOTIFICATION_STREAM_INTERVAL_SECONDS = 5


async def _reminder_worker() -> None:
    while True:
        try:
            case_service.generate_reminder_notifications()
        except Exception:
            logger.exception("Background deadline reminder check failed")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(_: FastAPI):
    auth_service.initialize_auth_storage()
    document_store.initialize_storage()
    case_service.initialize_case_storage()
    vector_store.initialize_vector_store()
    worker = asyncio.create_task(_reminder_worker())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Real-time legal research and compliance assistant API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


PUBLIC_AUTH_PATHS = {"/api/auth/bootstrap/status", "/api/auth/bootstrap", "/api/auth/login"}


@app.middleware("http")
async def enforce_api_auth(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in PUBLIC_AUTH_PATHS:
        return await call_next(request)
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return JSONResponse({"detail": "Authentication required."}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    user = auth_service.user_from_token(authorization[7:].strip())
    if not user:
        return JSONResponse({"detail": "Invalid or expired access token."}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    request.state.user = user
    role = user["role"]
    method = request.method
    required_roles = None
    if path.startswith("/api/auth/users") and method in {"GET", "POST", "PATCH"}:
        required_roles = {"admin"}
    elif path == "/api/documents" and method == "POST":
        required_roles = {"admin", "lawyer", "assistant"}
    elif path.startswith("/api/documents/") and path.endswith("/index") and method == "POST":
        required_roles = {"admin", "lawyer", "assistant"}
    elif path.startswith("/api/documents/") and path.count("/") == 3 and method == "DELETE":
        required_roles = {"admin", "lawyer"}
    elif path == "/api/cases" and method == "POST":
        required_roles = {"admin", "lawyer"}
    elif path.startswith("/api/cases/") and "/shares" in path and method in {"POST", "DELETE"}:
        required_roles = {"admin", "lawyer"}
    elif path.startswith("/api/cases/") and method == "PATCH":
        required_roles = {"admin", "lawyer"}
    elif path == "/api/deadlines" and method == "POST":
        required_roles = {"admin", "lawyer"}
    elif path.startswith("/api/deadlines/") and method == "PATCH":
        required_roles = {"admin", "lawyer"}
    elif path == "/api/reminders/run" and method == "POST":
        required_roles = {"admin"}
    if required_roles and role not in required_roles:
        return JSONResponse({"detail": "Your role does not have permission to perform this action."}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "no-store"
    return response


class BootstrapAdminRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class CreateUserRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "lawyer", "assistant", "viewer"]


class ActiveUserRequest(BaseModel):
    is_active: bool


class ShareDocumentRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    permission: Literal["read", "write"] = "read"


class ShareCaseRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    permission: Literal["read", "write"] = "read"


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    limit: int = Field(default=5, ge=1, le=10)


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    limit: int = Field(default=5, ge=1, le=8)


class CreateCaseRequest(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    case_number: str | None = Field(default=None, max_length=120)
    jurisdiction: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=3000)


class CaseStatusRequest(BaseModel):
    status: Literal["active", "closed", "archived"]


class CreateDeadlineRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=3, max_length=180)
    due_date: date
    source_document_id: str | None = Field(default=None, max_length=64)
    source_page: int | None = Field(default=None, ge=1)
    notes: str = Field(default="", max_length=2000)
    remind_days_before: int = Field(default=3, ge=0, le=30)
    user_confirmed: bool


class DeadlineStatusRequest(BaseModel):
    status: Literal["pending", "completed", "cancelled"]


def _embedding_error(exc: Exception) -> HTTPException:
    if isinstance(exc, embeddings.EmbeddingConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, embeddings.EmbeddingProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail="The embedding operation failed.")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "legal-ai-assistant"}


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Legal AI Assistant API", "docs": "/docs"}


@app.get("/api/auth/bootstrap/status", tags=["authentication"])
def auth_bootstrap_status() -> dict[str, bool]:
    return {"needs_bootstrap": auth_service.user_count() == 0}


@app.post("/api/auth/bootstrap", status_code=status.HTTP_201_CREATED, tags=["authentication"])
def bootstrap_first_admin(request: BootstrapAdminRequest) -> dict[str, object]:
    try:
        user = auth_service.bootstrap_admin(
            email=request.email, full_name=request.full_name, password=request.password
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=409, detail="An administrator has already been created.")
    return {"user": user, "message": "Administrator account created. Sign in to continue."}


@app.post("/api/auth/login", tags=["authentication"])
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()) -> dict[str, object]:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = auth_service.login_retry_after_seconds(client_ip)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts. Try again after the indicated delay.",
            headers={"Retry-After": str(retry_after)},
        )
    user = auth_service.authenticate(form.username, form.password)
    if not user:
        auth_service.record_login_failure(client_ip)
        raise HTTPException(status_code=401, detail="Incorrect email or password.",
                            headers={"WWW-Authenticate": "Bearer"})
    auth_service.clear_login_failures(client_ip)
    return {
        "access_token": auth_service.create_access_token(user),
        "token_type": "bearer",
        "user": user,
        "expires_in": settings.access_token_minutes * 60,
    }


@app.get("/api/auth/me", tags=["authentication"])
def current_user(request: Request) -> dict[str, object]:
    return request.state.user


@app.get("/api/auth/users", tags=["authentication"])
def get_users() -> dict[str, object]:
    users = auth_service.list_users()
    return {"items": users, "count": len(users)}


@app.post("/api/auth/users", status_code=status.HTTP_201_CREATED, tags=["authentication"])
def add_user(request: CreateUserRequest) -> dict[str, object]:
    try:
        return auth_service.create_user(
            email=request.email, full_name=request.full_name,
            password=request.password, role=request.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/auth/users/{user_id}/active", tags=["authentication"])
def update_user_active(user_id: str, request: ActiveUserRequest, http_request: Request) -> dict[str, object]:
    if user_id == http_request.state.user["id"] and not request.is_active:
        raise HTTPException(status_code=400, detail="You cannot disable your own account.")
    try:
        user = auth_service.set_user_active(user_id, request.is_active)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@app.post("/api/documents", status_code=status.HTTP_201_CREATED, tags=["documents"])
def upload_document(http_request: Request, file: UploadFile = File(...)) -> dict[str, object]:
    """Validate, extract, and store a PDF using a generated storage name."""
    original_name = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not original_name or not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="The uploaded file must be a PDF.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"PDF exceeds the {settings.max_upload_mb} MB upload limit.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="The file does not have a valid PDF signature.")

    try:
        with fitz.open(stream=content, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise HTTPException(status_code=400, detail="Password-protected PDFs are not supported yet.")
            page_count = pdf.page_count
            if page_count < 1:
                raise HTTPException(status_code=400, detail="The PDF contains no pages.")
            if page_count > settings.max_pdf_pages:
                raise HTTPException(status_code=413, detail=f"PDF exceeds the {settings.max_pdf_pages}-page limit.")
            extracted_text = "\n\n".join(
                f"[Page {index + 1}]\n{page.get_text('text')}" for index, page in enumerate(pdf)
            ).strip()
    except HTTPException:
        raise
    except (fitz.FileDataError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail="The uploaded PDF could not be opened or parsed.") from exc
    finally:
        file.file.close()

    document_id = str(uuid4())
    stored_filename = f"{document_id}.pdf"
    stored_path: Path = document_store.UPLOAD_DIR / stored_filename
    stored_path.write_bytes(content)
    record = document_store.build_document_record(
        document_id=document_id,
        owner_id=http_request.state.user["id"],
        original_filename=original_name[:255],
        stored_filename=stored_filename,
        size_bytes=len(content),
        content=content,
        page_count=page_count,
        extracted_text=extracted_text,
    )
    try:
        document_store.insert_document(record)
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="The document could not be saved.") from exc

    return {
        "id": document_id,
        "filename": record["original_filename"],
        "size_bytes": record["size_bytes"],
        "page_count": page_count,
        "extracted_characters": len(extracted_text),
        "text_extracted": bool(extracted_text),
        "indexed": False,
        "created_at": record["created_at"],
    }


@app.get("/api/documents", tags=["documents"])
def documents_list(http_request: Request) -> dict[str, object]:
    owner_id = http_request.state.user["id"]
    documents = document_store.list_documents(owner_id)
    for document in documents:
        document["indexed"] = vector_store.document_is_indexed(document["id"])
    return {"items": documents, "count": len(documents)}


@app.get("/api/documents/{document_id}", tags=["documents"])
def document_detail(document_id: str, http_request: Request) -> dict[str, object]:
    owner_id = http_request.state.user["id"]
    document = document_store.get_document(document_id, owner_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    document["indexed"] = vector_store.document_is_indexed(document_id)
    document.pop("owner_id", None)
    return document


@app.get("/api/documents/{document_id}/shares", tags=["documents"])
def list_document_shares(document_id: str, http_request: Request) -> dict[str, object]:
    shares = document_store.list_document_shares(document_id, http_request.state.user["id"])
    if shares is None:
        raise HTTPException(status_code=404, detail="Document not found or you are not its owner.")
    return {"items": shares, "count": len(shares)}


@app.post("/api/documents/{document_id}/shares", status_code=status.HTTP_201_CREATED, tags=["documents"])
def create_document_share(
    document_id: str,
    request: ShareDocumentRequest,
    http_request: Request,
) -> dict[str, object]:
    try:
        return document_store.share_document(
            document_id, http_request.state.user["id"], request.email, request.permission
        )
    except ValueError as exc:
        if str(exc).startswith("Document not found"):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/documents/{document_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["documents"])
def delete_document_share(document_id: str, user_id: str, http_request: Request) -> None:
    if not document_store.revoke_document_share(document_id, http_request.state.user["id"], user_id):
        raise HTTPException(status_code=404, detail="Document share not found.")
    return None


@app.post("/api/documents/{document_id}/index", tags=["search"])
def index_document(document_id: str, http_request: Request) -> dict[str, object]:
    owner_id = http_request.state.user["id"]
    document = document_store.get_document(document_id, owner_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document["access_level"] == "read":
        raise HTTPException(status_code=403, detail="This shared document has read-only access.")
    chunks = chunk_document_text(document["extracted_text"])
    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="No selectable text was found. Scanned PDFs need OCR, which is not supported yet.",
        )
    try:
        vectors = embeddings.embed_texts([chunk["text"] for chunk in chunks])
    except (embeddings.EmbeddingConfigurationError, embeddings.EmbeddingProviderError) as exc:
        raise _embedding_error(exc) from exc
    try:
        vector_store.replace_document_chunks(
            document_id=document_id,
            owner_id=document["owner_id"],
            filename=document["original_filename"],
            chunks=chunks,
            embeddings=vectors,
            model=settings.embedding_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="The document could not be indexed.") from exc
    return {"document_id": document_id, "filename": document["original_filename"], "chunks_indexed": len(chunks), "embedding_model": settings.embedding_model}


@app.post("/api/search", tags=["search"])
def semantic_search(request: SearchRequest, http_request: Request) -> dict[str, object]:
    owner_id = http_request.state.user["id"]
    document_ids = [item["id"] for item in document_store.list_documents(owner_id)]
    if vector_store.indexed_chunk_count(document_ids=document_ids) == 0:
        return {"query": request.query, "items": [], "count": 0, "message": "No indexed document chunks yet. Index a PDF first."}
    try:
        query_vector = embeddings.embed_texts([request.query])[0]
    except (embeddings.EmbeddingConfigurationError, embeddings.EmbeddingProviderError) as exc:
        raise _embedding_error(exc) from exc
    results = vector_store.search_chunks(query_vector, limit=request.limit, document_ids=document_ids)
    return {"query": request.query, "items": results, "count": len(results)}


@app.post("/api/chat", tags=["chat"])
def legal_document_chat(request: ChatRequest, http_request: Request) -> dict[str, object]:
    """Answer a question from retrieved document passages and return source metadata."""
    owner_id = http_request.state.user["id"]
    document_ids = [item["id"] for item in document_store.list_documents(owner_id)]
    if vector_store.indexed_chunk_count(document_ids=document_ids) == 0:
        return {
            "answer": "I cannot answer from your documents yet because no passages have been indexed. Upload a PDF and select Index first.",
            "sources": [],
            "message": "No indexed documents are available.",
        }
    try:
        query_vector = embeddings.embed_texts([request.question])[0]
    except (embeddings.EmbeddingConfigurationError, embeddings.EmbeddingProviderError) as exc:
        raise _embedding_error(exc) from exc

    retrieved = vector_store.search_chunks(query_vector, limit=request.limit, document_ids=document_ids)
    if not retrieved:
        return {
            "answer": "The indexed documents did not return a relevant passage for this question. I cannot establish an answer from the available sources.",
            "sources": [],
            "message": "No relevant passages were retrieved.",
        }

    sources: list[dict[str, object]] = []
    for index, result in enumerate(retrieved, start=1):
        sources.append({
            "source_id": f"S{index}",
            "document_id": result["document_id"],
            "filename": result["filename"],
            "page_start": result["page_start"],
            "page_end": result["page_end"],
            "score": result["score"],
            "text": result["text"],
            "excerpt": result["text"][:700],
        })
    try:
        answer = chat_service.generate_answer(request.question, sources)
    except chat_service.ChatConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except chat_service.ChatProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    public_sources = [
        {key: source[key] for key in ("source_id", "document_id", "filename", "page_start", "page_end", "score", "excerpt")}
        for source in sources
    ]
    return {
        "question": request.question,
        "answer": answer,
        "sources": public_sources,
        "disclaimer": "AI-generated research assistance. Verify the cited document passages and any legal conclusions.",
    }


@app.post("/api/chat/stream", tags=["chat"])
def legal_document_chat_stream(request: ChatRequest, http_request: Request) -> StreamingResponse:
    """Stream an answer using Server-Sent Events (SSE)."""
    owner_id = http_request.state.user["id"]
    document_ids = [item["id"] for item in document_store.list_documents(owner_id)]
    if vector_store.indexed_chunk_count(document_ids=document_ids) == 0:
        raise HTTPException(status_code=409, detail="Index a document before asking questions.")
    try:
        query_vector = embeddings.embed_texts([request.question])[0]
    except (embeddings.EmbeddingConfigurationError, embeddings.EmbeddingProviderError) as exc:
        raise _embedding_error(exc) from exc
    retrieved = vector_store.search_chunks(query_vector, limit=request.limit, document_ids=document_ids)
    if not retrieved:
        raise HTTPException(status_code=404, detail="No relevant source passages were found.")
    sources: list[dict[str, object]] = []
    for index, result in enumerate(retrieved, start=1):
        sources.append({
            "source_id": f"S{index}",
            "document_id": result["document_id"],
            "filename": result["filename"],
            "page_start": result["page_start"],
            "page_end": result["page_end"],
            "score": result["score"],
            "text": result["text"],
            "excerpt": result["text"][:700],
        })
    try:
        chat_service.ensure_chat_configured()
    except chat_service.ChatConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    public_sources = [
        {key: source[key] for key in ("source_id", "document_id", "filename", "page_start", "page_end", "score", "excerpt")}
        for source in sources
    ]

    def event_stream():
        yield f"event: sources\ndata: {json.dumps(public_sources, ensure_ascii=False)}\n\n"
        try:
            for fragment in chat_service.stream_answer(request.question, sources):
                yield f"event: token\ndata: {json.dumps({'text': fragment}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'disclaimer': 'AI-generated research assistance, not legal advice.'})}\n\n"
        except chat_service.ChatProviderError as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/cases", status_code=status.HTTP_201_CREATED, tags=["cases"])
def create_case(request: CreateCaseRequest, http_request: Request) -> dict[str, object]:
    if not request.title.strip():
        raise HTTPException(status_code=422, detail="Case title cannot be blank.")
    case = case_service.create_case(request.model_dump(), http_request.state.user["id"])
    case.pop("owner_id", None)
    return case


@app.get("/api/cases", tags=["cases"])
def get_cases(http_request: Request) -> dict[str, object]:
    items = case_service.list_cases(http_request.state.user["id"])
    for item in items:
        item.pop("owner_id", None)
    return {"items": items, "count": len(items)}


@app.get("/api/cases/{case_id}/shares", tags=["cases"])
def get_case_shares(case_id: str, http_request: Request) -> dict[str, object]:
    shares = case_service.list_case_shares(case_id, http_request.state.user["id"])
    if shares is None:
        raise HTTPException(status_code=404, detail="Case not found or you are not its owner.")
    return {"items": shares, "count": len(shares)}


@app.post("/api/cases/{case_id}/shares", status_code=status.HTTP_201_CREATED, tags=["cases"])
def create_case_share(case_id: str, request: ShareCaseRequest, http_request: Request) -> dict[str, object]:
    try:
        return case_service.share_case(
            case_id, http_request.state.user["id"], request.email, request.permission
        )
    except ValueError as exc:
        if str(exc).startswith("Case not found"):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/cases/{case_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["cases"])
def delete_case_share(case_id: str, user_id: str, http_request: Request) -> None:
    if not case_service.revoke_case_share(case_id, http_request.state.user["id"], user_id):
        raise HTTPException(status_code=404, detail="Case share not found.")
    return None


@app.get("/api/cases/{case_id}", tags=["cases"])
def get_case(case_id: str, http_request: Request) -> dict[str, object]:
    case = case_service.get_case(case_id, http_request.state.user["id"])
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    case.pop("owner_id", None)
    return case


@app.patch("/api/cases/{case_id}", tags=["cases"])
def update_case(case_id: str, request: CaseStatusRequest, http_request: Request) -> dict[str, object]:
    try:
        case = case_service.update_case_status(case_id, request.status, http_request.state.user["id"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    case.pop("owner_id", None)
    return case


@app.post("/api/deadlines", status_code=status.HTTP_201_CREATED, tags=["deadlines"])
def create_deadline(request: CreateDeadlineRequest, http_request: Request) -> dict[str, object]:
    if not request.title.strip():
        raise HTTPException(status_code=422, detail="Deadline title cannot be blank.")
    try:
        return case_service.create_deadline(request.model_dump(), http_request.state.user["id"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/deadlines", tags=["deadlines"])
def get_deadlines(
    http_request: Request,
    case_id: str | None = None,
    status: Literal["pending", "completed", "cancelled"] | None = None,
) -> dict[str, object]:
    items = case_service.list_deadlines(http_request.state.user["id"], case_id=case_id, status=status)
    return {"items": items, "count": len(items)}


@app.patch("/api/deadlines/{deadline_id}", tags=["deadlines"])
def update_deadline(deadline_id: str, request: DeadlineStatusRequest, http_request: Request) -> dict[str, object]:
    try:
        deadline = case_service.update_deadline_status(deadline_id, request.status, http_request.state.user["id"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if deadline is None:
        raise HTTPException(status_code=404, detail="Deadline not found.")
    return deadline


@app.get("/api/notifications", tags=["notifications"])
def get_notifications(http_request: Request, unread_only: bool = False, limit: int = 50) -> dict[str, object]:
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 100.")
    items = case_service.list_notifications(http_request.state.user["id"], unread_only=unread_only, limit=limit)
    return {"items": items, "count": len(items)}


@app.get("/api/notifications/stream", tags=["notifications"])
async def stream_notifications(http_request: Request) -> StreamingResponse:
    """Stream access-scoped notification snapshots and revalidate the token while connected."""
    owner_id = http_request.state.user["id"]
    authorization = http_request.headers.get("Authorization", "")
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""

    async def event_stream():
        last_payload = None
        while True:
            if await http_request.is_disconnected():
                break
            active_user = auth_service.user_from_token(token)
            if not active_user or active_user["id"] != owner_id:
                yield f"event: error\ndata: {json.dumps({'detail': 'Your session expired or access was revoked. Sign in again.'})}\n\n"
                break
            payload = {
                "items": case_service.list_notifications(owner_id, limit=10),
                "summary": case_service.dashboard_summary(owner_id),
            }
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if serialized != last_payload:
                yield f"event: snapshot\ndata: {serialized}\n\n"
                last_payload = serialized
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(NOTIFICATION_STREAM_INTERVAL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/notifications/{notification_id}/read", tags=["notifications"])
def read_notification(notification_id: str, http_request: Request) -> dict[str, object]:
    notification = case_service.mark_notification_read(notification_id, http_request.state.user["id"])
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return notification


@app.post("/api/reminders/run", tags=["notifications"])
def run_reminder_check(http_request: Request) -> dict[str, object]:
    created = case_service.generate_reminder_notifications(owner_id=http_request.state.user["id"])
    return {"notifications_created": created, "checked_at": datetime.now(timezone.utc).isoformat()}


@app.get("/api/activity", tags=["dashboard"])
def get_activity(http_request: Request, limit: int = 50) -> dict[str, object]:
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 100.")
    items = case_service.list_activity(http_request.state.user["id"], limit=limit)
    return {"items": items, "count": len(items)}


@app.get("/api/dashboard/summary", tags=["dashboard"])
def get_dashboard_summary(http_request: Request) -> dict[str, int]:
    return case_service.dashboard_summary(http_request.state.user["id"])


@app.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["documents"])
def document_delete(document_id: str, http_request: Request) -> None:
    owner_id = http_request.state.user["id"]
    document = document_store.get_document(document_id, owner_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document["access_level"] != "owner":
        raise HTTPException(status_code=403, detail="Only the document owner can delete it.")
    try:
        vector_store.remove_document_chunks(document_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="The document index could not be removed.") from exc
    if not document_store.delete_document(document_id, owner_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return None
