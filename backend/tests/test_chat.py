import pytest

from app.services.chat import (
    ChatProviderError,
    _citation_checked_answer,
    _format_context,
)


def test_context_formatter_uses_real_line_breaks_and_separates_sources():
    sources = [
        {
            "source_id": "S1",
            "filename": "notice.pdf",
            "page_start": 2,
            "page_end": 3,
            "text": "Written notice is required.",
        },
        {
            "source_id": "S2",
            "filename": "agreement.pdf",
            "page_start": 4,
            "page_end": 4,
            "text": "The agreement renews annually.",
        },
    ]

    context = _format_context(sources)

    assert "page(s) 2-3\nEXCERPT:\nWritten notice is required." in context
    assert "\n\n---\n\n" in context
    assert r"\nEXCERPT:" not in context
    assert "[S2] File: agreement.pdf" in context


def test_uncited_model_answer_is_rejected():
    sources = [{"source_id": "S1"}]
    with pytest.raises(ChatProviderError, match="verifiable source citation"):
        _citation_checked_answer("The notice period is 30 days.", sources)


def test_answer_with_valid_source_reference_is_preserved():
    sources = [{"source_id": "S1"}]
    assert _citation_checked_answer("Notice is required [S1].", sources) == "Notice is required [S1]."


def test_answer_with_only_unknown_source_reference_is_rejected():
    sources = [{"source_id": "S1"}]
    with pytest.raises(ChatProviderError, match="verifiable source citation"):
        _citation_checked_answer("Notice is required [S9].", sources)

[executed on device: NIDHIN (47c41d4b-ef60-4c09-8668-4cc72e1eff30)]