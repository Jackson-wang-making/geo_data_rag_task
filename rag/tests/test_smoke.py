"""Smoke checks for the PDF extraction + chunking skeleton (ticket 01)."""

from pathlib import Path

import pytest

from trendee_rag.knowledge import chunk_blocks, extract_pdf, file_hash

PDF = Path(__file__).resolve().parents[2] / "inputs" / "brand" / "Trendee品宣-公开版.pdf"


@pytest.fixture(scope="module")
def extracted():
    data = PDF.read_bytes()
    assert file_hash(data) == file_hash(data)
    return extract_pdf(data)


def test_bundled_pdf_is_parseable(extracted):
    blocks, info = extracted
    assert info["pages"] == 36
    assert blocks
    assert any(b["page"] == 4 and b["text"].strip() for b in blocks)
    # Page 29 is a divider with a short readable text layer plus a decorative
    # image; readable text means no OCR fallback is needed.
    assert 29 not in info["ocr_unavailable"]


def test_chunks_are_page_bounded(extracted):
    blocks, _ = extracted
    chunks, metas = chunk_blocks(blocks)
    assert chunks
    assert len(chunks) == len(metas)
    assert all(m["pdf_page"] is not None for m in metas)
    assert all(chunk.strip() for chunk in chunks)
    pages = {m["pdf_page"] for m in metas}
    assert {4, 36} <= pages
    assert 29 not in pages
