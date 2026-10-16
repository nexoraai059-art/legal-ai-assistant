"""Page-aware text chunking for source-grounded retrieval."""

import re
from typing import TypedDict


PAGE_MARKER = re.compile(r"\[Page\s+(\d+)\]")


class TextChunk(TypedDict):
    text: str
    page_start: int
    page_end: int
    chunk_index: int


def chunk_document_text(text: str, chunk_size: int = 1200, overlap: int = 160) -> list[TextChunk]:
    if chunk_size < 100 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Chunk size must be at least 100 and overlap must be smaller than chunk size.")
    markers = list(PAGE_MARKER.finditer(text))
    if not markers:
        clean = text.strip()
        return _chunk_page(clean, 1, chunk_size, overlap) if clean else []

    chunks: list[TextChunk] = []
    for marker_index, marker in enumerate(markers):
        page_number = int(marker.group(1))
        page_start = marker.end()
        page_end = markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(text)
        page_text = text[page_start:page_end].strip()
        if page_text:
            chunks.extend(_chunk_page(page_text, page_number, chunk_size, overlap, offset=len(chunks)))
    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index
    return chunks


def _chunk_page(text: str, page_number: int, chunk_size: int, overlap: int, offset: int = 0) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + chunk_size // 2, end), text.rfind(". ", start + chunk_size // 2, end))
            if boundary > start:
                end = boundary + (1 if text[boundary] == "\n" else 2)
        segment = text[start:end].strip()
        if segment:
            chunks.append({
                "text": f"[Page {page_number}]\n{segment}",
                "page_start": page_number,
                "page_end": page_number,
                "chunk_index": offset + len(chunks),
            })
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks