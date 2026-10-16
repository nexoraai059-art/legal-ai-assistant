import pytest

from app.services.pdf_processing import OcrPageLimitError, OcrUnavailableError, extract_page_text


class FakePage:
    def __init__(self, *, ocr_text="recognized legal text", fail_ocr=False):
        self.ocr_text = ocr_text
        self.fail_ocr = fail_ocr
        self.ocr_calls = []

    def get_textpage_ocr(self, *, language, dpi, full):
        self.ocr_calls.append({"language": language, "dpi": dpi, "full": full})
        if self.fail_ocr:
            raise RuntimeError("Tesseract not found")
        return "ocr-textpage"

    def get_text(self, kind, *, textpage=None):
        if textpage == "ocr-textpage":
            return self.ocr_text
        return ""


def test_ocr_enabled_recognizes_text_from_scanned_page():
    page = FakePage()

    text, used_ocr = extract_page_text(
        page,
        original_text="",
        ocr_enabled=True,
        language="eng",
        dpi=150,
        allow_ocr=True,
    )

    assert text == "recognized legal text"
    assert used_ocr is True
    assert page.ocr_calls == [{"language": "eng", "dpi": 150, "full": True}]


def test_ocr_disabled_leaves_image_only_page_unmodified():
    page = FakePage()

    text, used_ocr = extract_page_text(
        page,
        original_text="",
        ocr_enabled=False,
        language="eng",
        dpi=150,
        allow_ocr=True,
    )

    assert text == ""
    assert used_ocr is False
    assert page.ocr_calls == []


def test_selectable_text_skips_ocr_even_when_enabled():
    page = FakePage()
    selectable_text = "This page already contains selectable legal text."

    text, used_ocr = extract_page_text(
        page,
        original_text=selectable_text,
        ocr_enabled=True,
        language="eng",
        dpi=150,
        allow_ocr=True,
    )

    assert text == selectable_text
    assert used_ocr is False
    assert page.ocr_calls == []


def test_ocr_page_limit_stops_processing_before_calling_engine():
    page = FakePage()

    with pytest.raises(OcrPageLimitError, match="MAX_OCR_PAGES"):
        extract_page_text(
            page,
            original_text="",
            ocr_enabled=True,
            language="eng",
            dpi=150,
            allow_ocr=False,
        )

    assert page.ocr_calls == []


def test_missing_tesseract_returns_actionable_error():
    page = FakePage(fail_ocr=True)

    with pytest.raises(OcrUnavailableError, match="Install Tesseract OCR"):
        extract_page_text(
            page,
            original_text="",
            ocr_enabled=True,
            language="eng",
            dpi=150,
            allow_ocr=True,
        )