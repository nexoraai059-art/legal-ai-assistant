"""PDF text extraction helpers, including opt-in Tesseract OCR for scanned pages."""

from typing import Any


class OcrUnavailableError(RuntimeError):
    """Raised when OCR is enabled but the local OCR engine cannot run."""


class OcrPageLimitError(RuntimeError):
    """Raised when a document requires more OCR pages than configured."""


MIN_SELECTABLE_TEXT_CHARS = 20


def extract_page_text(
    page: Any,
    *,
    original_text: str,
    ocr_enabled: bool,
    language: str,
    dpi: int,
    allow_ocr: bool,
) -> tuple[str, bool]:
    """Return page text and whether OCR was used, without OCRing normal text pages."""
    if not ocr_enabled or len(original_text.strip()) >= MIN_SELECTABLE_TEXT_CHARS:
        return original_text, False
    if not allow_ocr:
        raise OcrPageLimitError("This PDF needs OCR on more pages than MAX_OCR_PAGES allows. Split the PDF or raise the limit.")

    try:
        text_page = page.get_textpage_ocr(language=language, dpi=dpi, full=True)
        return page.get_text("text", textpage=text_page), True
    except RuntimeError as exc:
        raise OcrUnavailableError(
            "OCR is enabled but Tesseract could not run. Install Tesseract OCR and ensure tesseract.exe is on PATH."
        ) from exc