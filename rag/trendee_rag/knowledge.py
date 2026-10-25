"""PDF extraction, CJK-aware chunking, hybrid retrieval, and the in-memory store.

Framework-agnostic — no Streamlit imports here so the pipeline stays portable.
The writer pipeline is added in a later ticket.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import faiss
import jieba
import numpy as np
import pymupdf
from rank_bm25 import BM25Okapi

from .embeddings import EmbeddingClient, EmbedError

jieba.setLogLevel(logging.ERROR)

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE_CHARS", 700))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP_CHARS", 100))
RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", 10))
MIN_DENSE_SCORE = float(os.environ.get("MIN_DENSE_SCORE", 0.35))
RRF_K = 60
MAX_CHUNKS_PER_PAGE = 3
OCR_LANGUAGES = os.environ.get("OCR_LANGUAGES", "chi_sim+eng")


# ==================== TEXT NORMALIZATION ====================
_ARABIC_CHARS = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
_LATIN_CHARS = re.compile(r"[A-Za-z]")
_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")  # incl. tatweel
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# Function words only add BM25 noise (they match everything); already in normalized form.
_STOPWORDS = set(
    "a an the of to in on at by for from with and or but not no is are was were be been being do does did "
    "has have had it its this that these those there their they them he she his her we our you your i me my "
    "what which who whom whose when where why how many much can could will would shall should may might must "
    "as if than then so such into about over under per also any all each some more most other only very "
    "的 了 和 与 及 或 在 是 为 对 等 中 上 下 我们 你们 他们 这个 那个 以及 一个 一种 可以 通过 进行 目前 "
    "同时 已经 不断 从而 因此 但是 并且 及其 其中 这些 那些 这种 那种 "
    "في من الي علي عن مع هذا هذه ذلك تلك التي الذي الذين هو هي هم ان او ما ماذا لا لم لن كل قد كان كانت "
    "ثم بين عند حتي كم هل اين متي كيف لماذا اي بعد قبل".split()
)

# Query-only fillers. They must not keep an unrelated topic "covered" merely
# because a slide happens to contain 如何/介绍/需要.
_QUERY_STOPWORDS = _STOPWORDS | {
    "如何", "为什么", "怎么", "怎样", "什么", "哪些", "是否",
    "介绍", "需要", "做", "写", "用", "讲", "说", "了解",
}
_PAGE_NUMBER = re.compile(r"^\s*(page|صفحة)?\s*\d{1,4}(\s*(/|of|من)\s*\d{1,4})?\s*$", re.IGNORECASE)

_CJK_RANGE = "㐀-䶿一-鿿぀-ヿ가-힯"
_CJK = re.compile(f"[{_CJK_RANGE}]")
_LATIN_WORD = re.compile(r"[A-Za-z0-9]+(?:[-_'][A-Za-z0-9]+)*")
# One CJK character, one Latin/number word, or any other single character. Costs nothing is lost.
_SPLIT_TOKEN = re.compile(f"[{_CJK_RANGE}]|{_LATIN_WORD.pattern}|.", re.DOTALL)


def clean_text(text: str) -> str:
    """NFKC folds Arabic presentation forms, ligatures and NBSPs into plain characters."""
    text = unicodedata.normalize("NFKC", text).replace("\xad", "-")
    text = _INVISIBLE.sub("", text)
    text = re.sub(r"\s+([\u064b-\u065f\u0670])", r"\1", text)  # re-attach detached Arabic marks
    return re.sub(r"[ \t]+", " ", text).strip()


def detect_lang(text: str) -> str:
    ar, la = len(_ARABIC_CHARS.findall(text)), len(_LATIN_CHARS.findall(text))
    if ar + la == 0:
        return "other"
    ratio = ar / (ar + la)
    return "ar" if ratio > 0.8 else "en" if ratio < 0.2 else "mixed"


def tokenize(text: str) -> List[str]:
    """BM25 tokens. CJK text uses jieba; other text keeps the baseline word tokenizer."""
    if _CJK.search(text):
        return [
            tok
            for tok in (w.strip().lower() for w in jieba.lcut(text))
            if tok and tok not in _STOPWORDS and re.search(r"\w", tok)
        ]
    text = _ARABIC_DIACRITICS.sub("", text.lower())
    text = re.sub("[إأآٱ]", "ا", text).replace("ى", "ي").replace("ة", "ه").translate(_DIGITS)
    tokens = []
    for tok in re.findall(r"\w+", text):
        if tok in _STOPWORDS:
            continue
        if len(tok) > 4 and tok.startswith(("ال", "وال")):
            tok = tok[2:] if tok.startswith("ال") else tok[3:]
        tokens.append(tok)
    return tokens


def _token_cost(token: str) -> int:
    """Length unit for chunking: CJK character = 1, Latin/number word = 1, punctuation = 0."""
    if len(token) == 1 and _CJK.match(token):
        return 1
    return 1 if _LATIN_WORD.fullmatch(token) else 0


def cjk_len(text: str) -> int:
    """Chinese-friendly length: CJK chars count 1, Latin words count 1, punctuation 0."""
    return sum(_token_cost(tok) for tok in _SPLIT_TOKEN.findall(text))


# ==================== PDF EXTRACTION ====================
def _find_tessdata() -> Optional[str]:
    candidates = [
        os.environ.get("TESSDATA_PREFIX", ""),
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tessdata",
        "/opt/homebrew/share/tessdata",
        "/usr/local/share/tessdata",
    ]
    for path in candidates:
        if path and Path(path, "eng.traineddata").exists():
            return path
    try:
        return pymupdf.get_tessdata()
    except Exception:
        return None


TESSDATA = _find_tessdata()


def _needs_ocr(page: pymupdf.Page, text: str) -> bool:
    """Scanned page: no extractable text, mostly unmapped glyphs, or almost no text plus an image."""
    visible = re.sub(r"\s", "", text)
    if not visible:
        return True
    if visible.count("\ufffd") / len(visible) > 0.3:
        return True
    # A divider slide can have a readable short caption plus decorative images.
    # Only tiny text runs are treated as an image-page fallback; 10+ readable
    # characters are enough to extract without OCR.
    return len(visible) < 10 and bool(page.get_images())


def _table_markdown(rows: List[List[Optional[str]]]) -> str:
    rows = [[clean_text(c or "").replace("\n", " ").replace("|", "/") for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _join_lines(lines: List[str], ocr: bool) -> str:
    """Join a block's lines into one paragraph; keep line-end hyphens attached; drop OCR speckle lines."""
    out = ""
    for line in lines:
        line = clean_text(line)
        if not line or (ocr and sum(ch.isalnum() for ch in line) < 3):
            continue
        out = out + line if out.endswith("-") else f"{out} {line}" if out else line
    return out


def _reading_order(blocks: List[dict], width: float, rtl: bool) -> List[dict]:
    """Order blocks column by column. Full-width blocks split the page into horizontal bands."""
    mid, tol = width / 2, width * 0.05

    def column(b: dict) -> int:
        x0, _, x1, _ = b["bbox"]
        if x1 <= mid + tol:
            return 0
        if x0 >= mid - tol:
            return 1
        return -1

    cols = [column(b) for b in blocks]
    if cols.count(0) < 2 or cols.count(1) < 2:  # single-column page
        return sorted(blocks, key=lambda b: (round(b["bbox"][1]), b["bbox"][0]))

    ordered, band = [], []
    first, second = (1, 0) if rtl else (0, 1)

    def flush():
        for c in (first, second):
            ordered.extend(sorted((b for b in band if column(b) == c), key=lambda b: b["bbox"][1]))
        band.clear()

    for b in sorted(blocks, key=lambda b: b["bbox"][1]):
        if column(b) == -1:
            flush()
            ordered.append(b)
        else:
            band.append(b)
    flush()
    return ordered


def extract_pdf(data: bytes) -> Tuple[List[dict], dict]:
    """Return (blocks, info). Each block: {page, text, kind: text|heading|table, ocr, size, bold}.

    PyMuPDF text layer first; per-page OCR fallback for scanned pages; tables → Markdown.
    """
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass and not doc.authenticate(""):
        raise ValueError("PDF is password-protected")

    blocks: List[dict] = []
    info = {"pages": doc.page_count, "ocr_pages": [], "ocr_unavailable": [], "tables": 0, "page_labels": {}}
    flags = (pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES) | pymupdf.TEXT_DEHYPHENATE

    for page in doc:
        pno = page.number + 1
        try:
            info["page_labels"][pno] = page.get_label() or str(pno)
        except Exception:
            info["page_labels"][pno] = str(pno)
        textpage, ocr = None, False
        if _needs_ocr(page, page.get_text()):
            if TESSDATA:
                try:
                    textpage = page.get_textpage_ocr(flags=flags, language=OCR_LANGUAGES, dpi=300, full=True, tessdata=TESSDATA)
                    ocr = True
                    info["ocr_pages"].append(pno)
                except Exception:
                    info["ocr_unavailable"].append(pno)
            else:
                info["ocr_unavailable"].append(pno)

        page_blocks: List[dict] = []
        table_boxes: List[pymupdf.Rect] = []
        if not ocr and len(page.get_cdrawings()) >= 4:  # ruled tables need vector lines; skips text-only pages
            try:
                for table in page.find_tables().tables:
                    if table.row_count < 2 or table.col_count < 2:
                        continue
                    md = _table_markdown(table.extract())
                    if md:
                        table_boxes.append(pymupdf.Rect(table.bbox))
                        page_blocks.append({"bbox": tuple(table.bbox), "text": md, "kind": "table", "size": 0, "bold": False})
            except Exception:
                pass  # table detection is best-effort

        d = page.get_text("dict", flags=flags, textpage=textpage)
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            rect = pymupdf.Rect(b["bbox"])
            center = (rect.tl + rect.br) / 2
            if any(center in tb for tb in table_boxes):
                continue
            spans = [s for line in b["lines"] for s in line["spans"] if s["text"].strip()]
            text = _join_lines(["".join(s["text"] for s in line["spans"]) for line in b["lines"]], ocr)
            if not spans or not text or _PAGE_NUMBER.match(text):
                continue
            page_blocks.append({
                "bbox": tuple(b["bbox"]),
                "text": text,
                "kind": "text",
                "size": round(max(s["size"] for s in spans), 1),
                "bold": all(s["flags"] & 16 for s in spans),
                "lines": len(b["lines"]),
            })

        rtl = detect_lang(" ".join(b["text"] for b in page_blocks)) == "ar"
        height = page.rect.height
        for b in _reading_order(page_blocks, page.rect.width, rtl):
            b.update(page=pno, ocr=ocr, margin=b["bbox"][3] < height * 0.12 or b["bbox"][1] > height * 0.88)
            blocks.append(b)

    blocks = _drop_running_headers(blocks, doc.page_count)
    _mark_headings(blocks)
    info["tables"] = sum(b["kind"] == "table" for b in blocks)
    return blocks, info


def _drop_running_headers(blocks: List[dict], pages: int) -> List[dict]:
    """Remove headers/footers: text repeated on many pages (digits ignored), or repeated in the page margins."""
    if pages < 3:
        return blocks
    key = lambda b: re.sub(r"\d+", "#", b["text"].lower())  # noqa: E731
    seen: dict = {}
    for b in blocks:
        seen.setdefault(key(b), set()).add(b["page"])
    return [
        b for b in blocks
        if not (len(seen[key(b)]) >= max(3, pages * 0.2) or (b["margin"] and len(seen[key(b)]) >= 3))
    ]


def _mark_headings(blocks: List[dict]) -> None:
    """Short blocks set in a larger (or bold) font than the body text become section headings."""
    sized = [(b["size"], len(b["text"])) for b in blocks if b["kind"] == "text" and not b["ocr"]]
    if not sized:
        return
    # Body size = the font size carrying the most characters.
    weights: dict = {}
    for size, n in sized:
        weights[size] = weights.get(size, 0) + n
    body = max(weights, key=weights.get)
    body_bold = statistics.mean(b["bold"] for b in blocks if b["kind"] == "text" and not b["ocr"]) > 0.5
    for b in blocks:
        if b["kind"] != "text" or b["ocr"]:
            continue
        short = len(b["text"]) <= 150 and b.get("lines", 1) <= 3 and not b["text"].endswith((".", ":", "،"))
        bigger = b["size"] >= body * 1.15
        if short and (bigger or (b["bold"] and not body_bold)) and re.search(r"\w", b["text"]):
            b["kind"] = "heading"

    # Some slides set a whole statement in display type. If every text block on a
    # page was classified as a heading, but the page still contains sentence
    # punctuation and enough content, treat it as body so the page is indexed.
    # Title-only dividers stay heading-only and remain a coverage gap.
    #
    # clean_text() applies NFKC during extraction, so full-width ！？； arrive
    # here as ASCII !?;. Match both forms or three of the four sentence marks
    # would silently disable the fallback. A single block is left as a heading:
    # without a separate title there is no page-level section to keep, and a
    # lone long title must not be indexed as if it were body copy.
    by_page: dict = {}
    for b in blocks:
        if b["kind"] in ("text", "heading") and not b["ocr"]:
            by_page.setdefault(b["page"], []).append(b)
    for page_blocks in by_page.values():
        if len(page_blocks) < 2 or not all(b["kind"] == "heading" for b in page_blocks):
            continue
        total = sum(cjk_len(b["text"]) for b in page_blocks)
        if total >= 40 and any(re.search(r"[。！？；!?;]", b["text"]) for b in page_blocks):
            # Keep the first block as the page's section heading; the rest is
            # display-size body copy that must reach the chunker.
            for b in page_blocks[1:]:
                b["kind"] = "text"


# ==================== CHUNKING ====================
def _overlap_tail(buf: List[str], overlap: int) -> Tuple[List[str], int]:
    """Trailing tokens of `buf` worth at most `overlap` length units."""
    if overlap <= 0:
        return [], 0
    tail: List[str] = []
    cost = 0
    for token in reversed(buf):
        token_cost = _token_cost(token)
        if cost + token_cost > overlap:
            break
        tail.append(token)
        cost += token_cost
    tail.reverse()
    while tail and not tail[0].strip():
        tail.pop(0)
    return tail, sum(_token_cost(t) for t in tail)


def _pack(paragraphs: List[str], size: int, overlap: int) -> List[str]:
    """Pack paragraphs into chunks measured by cjk_len; long Chinese text is windowed, never dropped."""
    chunks: List[str] = []
    buf: List[str] = []
    cost = 0
    fresh = False  # any token added since the last emit?
    for para in paragraphs:
        if buf:
            buf.append("\n")
        for token in _SPLIT_TOKEN.findall(para):
            token_cost = _token_cost(token)
            if cost + token_cost > size and buf:
                text = "".join(buf).strip()
                if text:
                    chunks.append(text)
                buf, cost = _overlap_tail(buf, overlap)
                fresh = False
            buf.append(token)
            cost += token_cost
            fresh = True
    text = "".join(buf).strip()
    if text and fresh:
        chunks.append(text)
    return [chunk for chunk in chunks if chunk.strip()]


def _split_table(md: str, size: int) -> List[str]:
    """Split long tables by rows, repeating the header row in every piece."""
    lines = md.split("\n")
    header, rows = lines[:2], lines[2:]
    pieces, cur = [], []
    for row in rows:
        if cur and cjk_len("\n".join(header + cur + [row])) > size:
            pieces.append("\n".join(header + cur))
            cur = []
        cur.append(row)
    if cur or not pieces:
        pieces.append("\n".join(header + cur))
    return pieces


def chunk_blocks(
    blocks: List[dict], chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP
) -> Tuple[List[str], List[dict]]:
    """Structure-aware chunking. Chunks never span pages; a new section starts a new chunk unless the
    current one is still tiny; tables stay whole (split by rows with the header repeated)."""
    chunks: List[str] = []
    metas: List[dict] = []
    section, chunk_section = "", ""
    paragraphs: List[str] = []
    has_body = False
    cur_page, cur_ocr = None, False
    min_units = max(chunk_size // 5, 8)

    def emit(text: str, kind: str, sec: str) -> None:
        if kind != "table" and (cjk_len(text) < 8 or text == sec):
            return  # stray fragment or a heading with no body on this page
        chunks.append(text)
        metas.append({"pdf_page": cur_page, "section": sec, "type": kind, "lang": detect_lang(text)})

    def flush() -> None:
        nonlocal has_body
        if has_body:  # a heading-only page (e.g. an image page) is a coverage gap, not evidence
            for text in _pack(paragraphs, chunk_size, chunk_overlap):
                emit(text, "ocr" if cur_ocr else "text", chunk_section)
        paragraphs.clear()
        has_body = False

    def add(text: str, body: bool = True) -> None:
        nonlocal chunk_section, has_body
        if not paragraphs:
            chunk_section = section
        paragraphs.append(text)
        if body:
            has_body = True

    for b in blocks:
        if b["page"] != cur_page:
            flush()
            cur_page, cur_ocr = b["page"], b["ocr"]
        if b["kind"] == "heading":
            if sum(cjk_len(p) for p in paragraphs) >= min_units:
                flush()
            section = b["text"][:150]
            add(b["text"], body=False)  # heading stays in the text so merged small sections keep their titles
        elif b["kind"] == "table":
            flush()
            for piece in _split_table(b["text"], chunk_size):
                emit(piece, "table", section)
        else:
            add(b["text"])
    flush()
    return chunks, metas


# ==================== STORE ====================
@dataclass
class RAGStore:
    """In-memory chunks, metadata, FAISS dense index, and BM25 sparse index."""

    chunks: List[str] = field(default_factory=list)
    doc_names: List[str] = field(default_factory=list)
    chunk_meta: List[dict] = field(default_factory=list)
    pdf_metadata: dict = field(default_factory=dict)
    embedding_model: str = ""
    dimension: int = 0
    index: Optional[faiss.Index] = None
    bm25: Optional[BM25Okapi] = None
    bm25_tokens: List[List[str]] = field(default_factory=list)
    embeddings: Optional[np.ndarray] = None

    @property
    def documents(self) -> List[str]:
        return sorted(set(self.doc_names))

    def has_document(self, name: str) -> bool:
        return name in self.pdf_metadata

    def find_by_hash(self, sha1: str) -> Optional[str]:
        return next((n for n, m in self.pdf_metadata.items() if m.get("sha1") == sha1), None)

    def add_document(self, doc_name: str, chunks: List[str], meta: dict, chunk_meta: Optional[List[dict]] = None) -> None:
        self.chunks.extend(chunks)
        self.doc_names.extend([doc_name] * len(chunks))
        self.chunk_meta.extend(
            chunk_meta or [{"pdf_page": None, "section": "", "type": "text"} for _ in chunks]
        )
        self.pdf_metadata[doc_name] = meta

    def index_text(self, i: int) -> str:
        """Text that gets embedded / BM25-indexed: section heading gives each chunk its context."""
        section = self.chunk_meta[i].get("section") if i < len(self.chunk_meta) else ""
        text = self.chunks[i]
        return f"{section}\n{text}" if section and not text.startswith(section) else text


@dataclass
class IngestReport:
    doc_name: str
    pages_total: int
    pages_with_chunks: List[int]
    pages_without_chunks: List[int]
    ocr_pages: List[int]
    ocr_unavailable_pages: List[int]
    chunk_count: int
    coverage_status: str

    def as_dict(self) -> dict:
        return {
            "doc_name": self.doc_name,
            "pages_total": self.pages_total,
            "pages_with_chunks": self.pages_with_chunks,
            "pages_without_chunks": self.pages_without_chunks,
            "ocr_pages": self.ocr_pages,
            "ocr_unavailable_pages": self.ocr_unavailable_pages,
            "chunk_count": self.chunk_count,
            "coverage_status": self.coverage_status,
        }


def ingest_pdf(
    data: bytes,
    embedder: EmbeddingClient,
    doc_name: str = "document.pdf",
) -> Tuple[RAGStore, IngestReport]:
    """PDF → blocks → page-bounded chunks → embeddings + FAISS + BM25.

    Raises EmbedError before returning any store if the embedding service is unusable.
    """
    try:
        blocks, info = extract_pdf(data)
    except Exception as exc:
        raise ValueError(f"无法读取 PDF：{exc}") from exc
    if info["pages"] == 0:
        raise ValueError("PDF 没有页面。")

    chunks, metas = chunk_blocks(blocks)

    # Deduplicate identical text on the same page (running headers etc. survive extraction).
    kept_chunks: List[str] = []
    kept_metas: List[dict] = []
    seen: set = set()
    for text, meta in zip(chunks, metas):
        key = (meta["pdf_page"], hashlib.sha1(re.sub(r"\s+", "", text).encode("utf-8")).hexdigest())
        if key in seen:
            continue
        seen.add(key)
        kept_chunks.append(text)
        kept_metas.append(meta)

    page_ordinals: dict = defaultdict(int)
    for text, meta in zip(kept_chunks, kept_metas):
        page = meta["pdf_page"]
        page_ordinals[page] += 1
        section = meta.get("section") or ""
        meta.update(
            chunk_id=f"{doc_name}#p{page}#c{page_ordinals[page]:03d}",
            doc_name=doc_name,
            page_label=info["page_labels"].get(page, str(page)),
            text=text,
            index_text=f"{section}\n{text}" if section and not text.startswith(section) else text,
            char_count=cjk_len(text),
        )

    store = RAGStore()
    store.add_document(
        doc_name,
        kept_chunks,
        {
            "pages": info["pages"],
            "ocr_pages": info["ocr_pages"],
            "ocr_unavailable": info["ocr_unavailable"],
            "tables": info["tables"],
            "num_chunks": len(kept_chunks),
            "total_text_length": sum(len(text) for text in kept_chunks),
            "sha1": file_hash(data),
        },
        kept_metas,
    )

    if kept_chunks:
        embedder.health()  # fail before building a partial index
        vectors = embedder.encode([meta["index_text"] for meta in kept_metas])
        if vectors.ndim != 2 or vectors.shape[0] != len(kept_chunks):
            raise EmbedError("EMBED_BAD_RESPONSE", "Embedding 数量与 chunk 数量不一致。")
        faiss.normalize_L2(vectors)
        store.embedding_model = embedder.model_id
        store.dimension = int(vectors.shape[1])
        store.embeddings = vectors
        store.index = faiss.IndexFlatIP(store.dimension)
        store.index.add(vectors)
        store.bm25_tokens = [tokenize(meta["index_text"]) for meta in kept_metas]
        store.bm25 = BM25Okapi(store.bm25_tokens)

    with_chunks = sorted({meta["pdf_page"] for meta in kept_metas})
    without_chunks = [page for page in range(1, info["pages"] + 1) if page not in set(with_chunks)]
    if not kept_chunks:
        coverage = "empty"
    elif without_chunks or info["ocr_unavailable"]:
        coverage = "partial"
    else:
        coverage = "complete"

    report = IngestReport(
        doc_name=doc_name,
        pages_total=info["pages"],
        pages_with_chunks=with_chunks,
        pages_without_chunks=without_chunks,
        ocr_pages=info["ocr_pages"],
        ocr_unavailable_pages=info["ocr_unavailable"],
        chunk_count=len(kept_chunks),
        coverage_status=coverage,
    )
    return store, report


# ==================== RETRIEVAL ====================
def search(
    store: RAGStore,
    embedder: EmbeddingClient,
    query: str,
    k: int = RETRIEVAL_TOP_K,
    min_dense: float = MIN_DENSE_SCORE,
) -> List[dict]:
    """Dense + BM25 ranking fused with RRF, filtered by an evidence floor."""
    query = query.strip()
    if not query or not store.chunks or store.index is None:
        return []

    query_tokens = tokenize(query)
    corpus_tokens = set().union(*(set(tokens) for tokens in store.bm25_tokens)) if store.bm25_tokens else set()
    content_tokens = {token for token in query_tokens if token not in _QUERY_STOPWORDS}
    if content_tokens and corpus_tokens and not (content_tokens & corpus_tokens):
        # The topic has no lexical anchor anywhere in the corpus. Dense scores
        # alone are not an evidence floor: bge-m3 gives unrelated Chinese text
        # around 0.4 cosine. Return no evidence so the writer fails closed with
        # `insufficient` instead of calling the writing model.
        return []

    query_vec = embedder.encode([query])
    if query_vec.shape[1] != store.dimension:
        raise EmbedError(
            "EMBED_DIMENSION_MISMATCH",
            f"查询向量维度 {query_vec.shape[1]} 与索引维度 {store.dimension} 不一致。",
        )
    faiss.normalize_L2(query_vec)

    n = len(store.chunks)
    scores, indices = store.index.search(query_vec, n)
    dense_scores = np.full(n, -1.0, dtype=np.float32)
    for score, idx in zip(scores[0], indices[0]):
        if idx >= 0:
            dense_scores[idx] = score

    bm25_scores = (
        np.asarray(store.bm25.get_scores(query_tokens), dtype=np.float32)
        if store.bm25 is not None
        else np.zeros(n, dtype=np.float32)
    )
    dense_rank = {idx: rank for rank, idx in enumerate(np.argsort(-dense_scores), start=1)}
    bm25_order = [idx for idx in np.argsort(-bm25_scores) if bm25_scores[idx] > 0]
    bm25_rank = {idx: rank for rank, idx in enumerate(bm25_order, start=1)}
    query_token_set = set(query_tokens)

    candidates: List[Tuple[int, float]] = []
    for idx in range(n):
        overlap = len(query_token_set & set(store.bm25_tokens[idx])) if query_token_set else 0
        dense_ok = dense_scores[idx] >= min_dense
        bm25_ok = idx in bm25_rank and overlap >= 2
        if not (dense_ok or bm25_ok):
            continue
        rrf = 1.0 / (RRF_K + dense_rank[idx])
        if idx in bm25_rank:
            rrf += 1.0 / (RRF_K + bm25_rank[idx])
        candidates.append((idx, rrf))
    candidates.sort(key=lambda item: (-item[1], -dense_scores[item[0]]))

    # At most 3 chunks per page unless there are not enough pages to fill k.
    picked: List[Tuple[int, float]] = []
    deferred: List[Tuple[int, float]] = []
    per_page: dict = defaultdict(int)
    for idx, rrf in candidates:
        page = store.chunk_meta[idx]["pdf_page"]
        if per_page[page] < MAX_CHUNKS_PER_PAGE:
            picked.append((idx, rrf))
            per_page[page] += 1
        else:
            deferred.append((idx, rrf))
    if len(picked) < k:
        picked.extend(deferred[: k - len(picked)])
    picked = sorted(
        picked, key=lambda item: (-item[1], -dense_scores[item[0]])
    )[:k]

    results = []
    for idx, rrf in picked:
        meta = store.chunk_meta[idx]
        results.append(
            {
                "doc_name": store.doc_names[idx],
                "pdf_page": meta["pdf_page"],
                "page_label": meta["page_label"],
                "section": meta.get("section", ""),
                "type": meta.get("type", "text"),
                "text": store.chunks[idx],
                "dense_score": float(dense_scores[idx]),
                "rrf_score": float(rrf),
                "score": float(rrf),
            }
        )
    return results


def file_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()
