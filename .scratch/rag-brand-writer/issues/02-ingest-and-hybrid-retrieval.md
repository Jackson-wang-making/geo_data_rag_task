# 02: Ingest the Trendee PDF and retrieve evidence with hybrid search

**What to build:** Opening the app auto-loads the bundled Trendee PDF, chunks it page-bounded with CJK-aware sizing, embeds it through local sentence-transformers `bge-m3` by default (Docker Ollama is optional), and builds FAISS dense plus jieba BM25 indexes. A user can enter a topic and see ranked evidence with doc name, PDF page, section, excerpt, and score. The UI reports page coverage (36 pages, pages without chunks including 8 and 29, OCR-unavailable pages). Uploading another PDF re-ingests it. When the embedding service is unavailable, the app shows an actionable error instead of a partial index.

**Blocked by:** 01 — Prefactor: slim the ChatPDF baseline into a light skeleton

**Status:** done

- [x] Opening the app indexes the bundled PDF without manual upload and shows total pages, pages with chunks, pages without chunks, OCR-unavailable pages, and chunk count.
- [x] A 1200-character Chinese paragraph without spaces produces at least two chunks and is never dropped; no chunk spans a page.
- [x] A topic query returns evidence from multiple pages/sections, each with canonical doc name, PDF page, page label, section, type, text, dense score, RRF score, and final score fields.
- [x] BM25 retrieval works on Chinese queries through jieba tokenization; hybrid RRF ranking is used by default.
- [x] Stopping the embedding service produces an actionable `EMBED_UNAVAILABLE` error and no index.
- [x] Ingestion seam tests pass with a fake embedder (page-bounded chunks, CJK long paragraph, coverage report, empty/encrypted PDF).

**Verification:** `pytest -q` reports 72 passed; ingest seam tests use a fake embedder. Real ingestion ran through the UI with both providers: local `bge-m3` (`EMBEDDING_PROVIDER=local`, CPU, 1024-dim) and Docker Ollama `bge-m3` (`trendee-ollama`, 1024-dim); both produce 36 PDF pages, 33 pages with chunks, pages 1/8/29 without chunks, no OCR-unavailable pages, 43 chunks, coverage `partial`. Page 18's display-size statement is recovered by the heading fallback; page 29 is a divider with readable text and does not need OCR. The fallback gate matches both full-width `！？；` and their NFKC-folded ASCII forms (`clean_text()` runs NFKC during extraction), and a page with only one heading block is never demoted, so a lone long title cannot create a false chunk. Boundary tests pin exactly 2 blocks and exactly 40 cjk_len (with 39 as the negative case), and assert page 18 keeps its title as `section` while page 19 uses its own heading. Live retrieval for the exam topic returned 10 sources across pages 4/12/14/16/19/25/31/32/33/34 with dense scores 0.501–0.624. The unrelated Rust topic returns no evidence after the lexical topic-anchor gate.

**Live-only evidence:** The default local sentence-transformers path was re-run from outside the project directory (`C:/Users/Jack`): `provider=local`, 43 chunks, 1024 dims, 10 results. The optional Docker Ollama image/container/model are also running (`ollama/ollama:latest`, `trendee-ollama`, `bge-m3:latest`); `/api/embed` returns 1024 dimensions with L2 norm 1.0. Uploading a different PDF (Raku 6.d brochure, 9 pages, 1.48 MB) through the real upload control re-indexed to 9/8/1/0/16 and retrieval returned 10 sources across 7 pages, all from the new document. Screenshots `05-upload-reindex.png`, `06-upload-retrieval.png`, `12-local-embed-unavailable.png` (default local failure), `10-embed-unavailable.png` (optional Ollama outage); details in `rag/docs/verification.md`.
