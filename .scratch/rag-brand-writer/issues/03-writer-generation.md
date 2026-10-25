# 03: Generate a structured Chinese article with DeepSeek

**What to build:** A user selects one of four content types (blog, faq, brand_intro, product_intro), enters a topic, and receives a structured Chinese Markdown article generated from the retrieved evidence. The writer builds numbered `[n]` context, calls DeepSeek non-streaming, checks `finish_reason`, and renders the article in the UI. Blog requires a title, intro, at least two H2 headings, and a conclusion; FAQ requires at least three Q/A pairs. A length-truncated response and a missing/invalid LLM configuration fail closed rather than producing a fake article.

**Blocked by:** 02 — Ingest the Trendee PDF and retrieve evidence with hybrid search

**Status:** done

- [x] The exam topic with Blog produces a Chinese Markdown article with title, intro, at least two H2 headings, and conclusion, using only retrieved evidence.
- [x] All four content types produce their required structures.
- [x] The context uses stable `[n]` numbering that matches the retrieved sources.
- [x] `finish_reason=length` maps to a partial/truncated result, never a success.
- [x] A missing key, auth failure, or provider error returns `LLM_UNAVAILABLE` and shows no generated article.
- [x] Writing seam tests pass with a fake LLM (happy path, structure, truncation, provider failure).
- [x] The article is explicitly marked provisional because citation validation is not yet implemented. *(Superseded by 04: the provisional label was removed when real citation validation and entailment landed.)*

**Verification:** `pytest -q` reports 72 passed; fake-LLM writing seam tests cover all four content types, truncation, structure failure, and provider failure. Real DeepSeek generation ran with `deepseek-flash` and prompt `2026-10-25.2`. UI Blog run `20261025-163101-608707` produced H1, intro, H2 sections and a conclusion with 10 numbered sources, `finish_reason=stop`, status `complete`. Real CLI runs cover the other content types: FAQ `20261025-162006-879084` (`partial`, 12 claims, `c001` unsupported), brand_intro `20261025-163405-720509` (`complete`, 12/12 supported), and product_intro `20261025-164140-277286` (`partial`, repaired then 17/17 supported). Artifacts are in `rag/examples/content-types/`; full validation results are in ticket 04 and `rag/docs/verification.md`.
