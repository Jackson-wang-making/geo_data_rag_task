# 05: Ship artifacts, examples, README, and cleanup

**What to build:** Each generation writes an article Markdown file with a source appendix and an evidence JSON file containing the model, parameters, sources, validation state, coverage, and finish reason. The UI offers downloads for both. The repository includes a real example article, evidence JSON, and screenshots generated from the Trendee PDF. The README explains the architecture, setup, the verbatim writer prompt, chunk/retrieval/citation strategies, known limitations, and ChatPDF's MIT attribution. Unused provider code and the upstream demo video are removed.

**Blocked by:** 04 — Validate citations, run entailment, and fail closed

**Status:** done

- [x] Every run writes article Markdown and evidence JSON, and both are downloadable from the UI.
- [x] The article appendix contains `[n]`, document name, PDF page, section, and excerpt.
- [x] A real example article and evidence JSON are committed with verifiable page citations.
- [x] 2–3 screenshots show ingest coverage, a generated article with sources, and an insufficient-evidence or partial state.
- [x] The README lets a fresh machine start local bge-m3 (or optional Docker Ollama), configure DeepSeek, run the app, and reproduce the example.
- [x] The README includes the exact writer prompt, design trade-offs, limitations, and MIT attribution.
- [x] The manual end-to-end checklist passes and unused provider/demo assets are removed.

**Verification:** artifacts, downloads, README, prompt text, strategies, limitations, and MIT attribution are implemented. `pytest -q` reports 72 passed, including artifact writing and both embedding providers; the Streamlit server boots on `127.0.0.1`. Unused provider code was archived during ticket 01, and the upstream ChatPDF demo GIF/MP4 were moved out of the deliverable into the local-only archive `.omx/archive/rag-upstream/`.

Real example output and screenshots now exist: `rag/examples/article.md`, `rag/examples/evidence.json`, `rag/examples/README.md`, and screenshots `01-coverage.png`, `02-article.png`, `03-sources.png` come from UI run `20261025-153905-378062` (local `bge-m3` + `deepseek-flash`). The run passed deterministic citations, returned 10/10 `supported` from entailment, did not trigger a repair, and reached `complete`. `04-insufficient.png` comes from the separate fail-closed run `20261025-153911-888736` (Rust topic, `status: insufficient`), because one complete run cannot also produce an insufficient screenshot; its artifact path is visible in the image. Citations were checked against the PDF: `27%` on page 33, `20%`/`30 天`/`300+` on page 32, `65%+`/Top 1 on page 34, matching the article appendix. Other live runs produced `partial` (one `uncertain` verdict, or a residual deterministic issue after repair), which is documented in `examples/README.md` rather than hidden.

The manual E2E checklist is now fully checked, including upload of another PDF (`05`/`06`), default local bge-m3 retrieval, optional Docker Ollama, FAQ/brand/product real generation (`examples/content-types/`), missing key (`09`), default local model load failure (`12`), optional Ollama outage (`10`), verifier failure matrix (`ALL_CASES_PASSED=1`), prompt injection, actual download clicks (`07`/`08`), and a UI FAQ `partial` with the “需要人工复核” expander (`11`). Details and run IDs are in `rag/docs/verification.md`.
