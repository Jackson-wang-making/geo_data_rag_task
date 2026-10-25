"""Ingestion seam tests: chunking, coverage, indexing, and retrieval with a fake embedder."""

from pathlib import Path

import numpy as np
import pymupdf
import pytest

from trendee_rag.embeddings import EmbedError
from trendee_rag.knowledge import (
    CHUNK_SIZE,
    _mark_headings,
    chunk_blocks,
    cjk_len,
    clean_text,
    ingest_pdf,
    search,
    tokenize,
)

PDF = Path(__file__).resolve().parents[2] / "inputs" / "brand" / "Trendee品宣-公开版.pdf"


class FakeEmbedder:
    model_id = "fake-embedder"
    dimension = 64

    def __init__(self, fail_health: bool = False):
        self.fail_health = fail_health

    def health(self) -> None:
        if self.fail_health:
            raise EmbedError("EMBED_UNAVAILABLE", "fake embedding service is down")

    def encode(self, texts):
        vectors = []
        for text in texts:
            vec = np.zeros(self.dimension, dtype=np.float32)
            for char in text:
                vec[ord(char) % self.dimension] += 1
            norm = np.linalg.norm(vec)
            vectors.append(vec if norm == 0 else vec / norm)
        return np.stack(vectors).astype(np.float32)


@pytest.fixture(scope="module")
def ingested():
    return ingest_pdf(PDF.read_bytes(), FakeEmbedder(), PDF.name)


def test_coverage_report(ingested):
    store, report = ingested
    assert report.pages_total == 36
    assert len(report.pages_with_chunks) == 33
    assert report.chunk_count == len(store.chunks) == 43
    assert report.pages_with_chunks == sorted({meta["pdf_page"] for meta in store.chunk_meta})
    assert 29 not in report.ocr_unavailable_pages  # readable divider text, no OCR needed
    assert report.pages_without_chunks == [1, 8, 29]
    assert report.coverage_status == "partial"


def test_chunk_metadata_is_canonical(ingested):
    store, _ = ingested
    meta = store.chunk_meta[0]
    for key in (
        "chunk_id",
        "doc_name",
        "pdf_page",
        "page_label",
        "section",
        "type",
        "text",
        "index_text",
        "char_count",
    ):
        assert key in meta
    assert meta["text"] == store.chunks[0]
    assert meta["char_count"] == cjk_len(meta["text"])
    assert len({m["chunk_id"] for m in store.chunk_meta}) == len(store.chunks)
    assert all(m["pdf_page"] is not None for m in store.chunk_meta)


def test_long_chinese_paragraph_is_split_not_dropped():
    block = {
        "page": 1,
        "text": "品" * 1200,
        "kind": "text",
        "ocr": False,
        "size": 10,
        "bold": False,
        "lines": 1,
    }
    chunks, metas = chunk_blocks([block])
    assert len(chunks) >= 2
    assert all(cjk_len(chunk) <= CHUNK_SIZE for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) >= 1200
    assert all(meta["pdf_page"] == 1 for meta in metas)


def test_display_type_slide_statement_is_indexed(ingested):
    store, _ = ingested
    assert 18 in {meta["pdf_page"] for meta in store.chunk_meta}
    assert any("记忆标签" in chunk for chunk in store.chunks)


def _display_block(page, text, size=32.0, lines=1):
    return {
        "page": page,
        "text": clean_text(text),
        "kind": "text",
        "ocr": False,
        "size": size,
        "bold": False,
        "lines": lines,
    }


def _body_page():
    # Establishes 10pt as the body size, so 32pt display blocks are headings.
    return {
        "page": 2,
        "text": "正" * 200,
        "kind": "text",
        "ocr": False,
        "size": 10.0,
        "bold": False,
        "lines": 1,
    }


@pytest.mark.parametrize("mark", ["！", "？", "；", "!", "?", ";"])
def test_display_fallback_accepts_nfkc_sentence_marks(mark):
    # Extraction runs NFKC, so full-width marks reach the gate as ASCII.
    blocks = [
        _display_block(1, "重新定义AI时代品牌竞争力"),
        _display_block(1, "新的竞争高地不再是网页排名和流量"),
        _display_block(1, "而是品牌在AI神经网络中的记忆标签" + mark),
        _body_page(),
    ]
    _mark_headings(blocks)
    assert blocks[0]["kind"] == "heading"
    assert blocks[1]["kind"] == "text"
    assert blocks[2]["kind"] == "text"


def test_single_heading_block_is_not_demoted():
    blocks = [
        _display_block(1, "数据" * 30 + "。"),
        _body_page(),
    ]
    _mark_headings(blocks)
    # A lone display block has no separate title to preserve; indexing it as
    # body would turn a long title-only page into a false coverage claim.
    assert blocks[0]["kind"] == "heading"


def test_display_fallback_requires_two_blocks_and_40_units():
    # Pin both gates: exactly 2 blocks and exactly 40 cjk_len must trigger.
    blocks = [
        _display_block(1, "甲" * 20),
        _display_block(1, "乙" * 20 + "。"),
        _body_page(),
    ]
    assert cjk_len(blocks[0]["text"]) + cjk_len(blocks[1]["text"]) == 40
    _mark_headings(blocks)
    assert blocks[0]["kind"] == "heading"
    assert blocks[1]["kind"] == "text"


def test_display_fallback_does_not_trigger_below_40_units():
    blocks = [
        _display_block(1, "甲" * 20),
        _display_block(1, "乙" * 19 + "。"),
        _body_page(),
    ]
    assert cjk_len(blocks[0]["text"]) + cjk_len(blocks[1]["text"]) == 39
    _mark_headings(blocks)
    assert blocks[0]["kind"] == "heading"
    assert blocks[1]["kind"] == "heading"


def test_display_fallback_keeps_page_section(ingested):
    store, _ = ingested
    page18 = [m for m in store.chunk_meta if m["pdf_page"] == 18]
    page19 = [m for m in store.chunk_meta if m["pdf_page"] == 19]
    # The first display block stays the page's section heading; the next page
    # must use its own heading rather than inheriting page 18's statement.
    assert page18 and page18[0]["section"].startswith("重新定义AI时代品牌竞争力")
    assert page19 and all(m["section"].startswith("LLM-原生GEO") for m in page19)


def test_jieba_tokenizes_chinese():
    tokens = tokenize("品牌出海与GEO优化")
    assert "品牌" in tokens
    assert "优化" in tokens


def test_search_returns_canonical_evidence(ingested):
    store, _ = ingested
    results = search(store, FakeEmbedder(), "GEO 优化", k=5)
    assert results
    assert len({result["pdf_page"] for result in results}) >= 2
    for result in results:
        for key in (
            "doc_name",
            "pdf_page",
            "page_label",
            "section",
            "type",
            "text",
            "dense_score",
            "rrf_score",
            "score",
        ):
            assert key in result
        assert 1 <= result["pdf_page"] <= 36
        assert result["text"] in store.chunks


def test_unrelated_topic_returns_no_evidence(ingested):
    store, _ = ingested
    results = search(store, FakeEmbedder(), "如何用 Rust 写一个操作系统内核", k=10)

    assert results == []


def test_empty_and_encrypted_pdfs_raise():
    with pytest.raises(ValueError):
        ingest_pdf(b"", FakeEmbedder())

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "confidential")
    encrypted = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    with pytest.raises(ValueError):
        ingest_pdf(encrypted, FakeEmbedder())


def test_embedding_failure_builds_no_index():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Trendee is a brand growth platform. " * 30)
    data = doc.tobytes()

    with pytest.raises(EmbedError) as exc:
        ingest_pdf(data, FakeEmbedder(fail_health=True))
    assert exc.value.code == "EMBED_UNAVAILABLE"
