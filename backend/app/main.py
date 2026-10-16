from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import documents as document_store
from app.services import embeddings, vector_store
from app.services.chunking import chunk_document_text


@asynccontextmanager
async def lifespan(_: FastAPI):
    document_store.initialize_storage()
    vector_store.initialize_vector_store()
    yield


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


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    limit: int = Field(default=5, ge=1, le=10)


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


@app.post("/api/documents", status_code=status.HTTP_201_CREATED, tags=["documents"])
def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
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
def documents_list() -> dict[str, object]:
    documents = document_store.list_documents()
    for document in documents:
        document["indexed"] = vector_store.document_is_indexed(document["id"])
    return {"items": documents, "count": len(documents)}


@app.get("/api/documents/{document_id}", tags=["documents"])
def document_detail(document_id: str) -> dict[str, object]:
    document = document_store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    document["indexed"] = vector_store.document_is_indexed(document_id)
    return document


@app.post("/api/documents/{document_id}/index", tags=["search"])
def index_document(document_id: str) -> dict[str, object]:
    document = document_store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
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
            filename=document["original_filename"],
            chunks=chunks,
            embeddings=vectors,
            model=settings.embedding_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="The document could not be indexed.") from exc
    return {"document_id": document_id, "filename": document["original_filename"], "chunks_indexed": len(chunks), "embedding_model": settings.embedding_model}


@app.post("/api/search", tags=["search"])
def semantic_search(request: SearchRequest) -> dict[str, object]:
    if vector_store.indexed_chunk_count() == 0:
        return {"query": request.query, "items": [], "count": 0, "message": "No indexed document chunks yet. Index a PDF first."}
    try:
        query_vector = embeddings.embed_texts([request.query])[0]
    except (embeddings.EmbeddingConfigurationError, embeddings.EmbeddingProviderError) as exc:
        raise _embedding_error(exc) from exc
    results = vector_store.search_chunks(query_vector, limit=request.limit)
    return {"query": request.query, "items": results, "count": len(results)}


@app.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["documents"])
def document_delete(document_id: str) -> None:
    if document_store.get_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        vector_store.remove_document_chunks(document_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="The document index could not be removed.") from exc
    if not document_store.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return None