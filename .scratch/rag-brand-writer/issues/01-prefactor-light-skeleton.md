# 01: Prefactor — slim the ChatPDF baseline into a light skeleton

**What to build:** A bootable light Streamlit shell that retains the existing PDF extraction path while removing the chat loop, cloud-provider branches, index persistence, reranker, and unused heavy dependencies. The project instructions point at the light spec, and the heavy planning docs are archived rather than deleted. This ticket delivers no new writing behaviour; it makes every later slice small enough to land cleanly.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] `streamlit run app.py` starts without importing sentence-transformers, torch, or fpdf2.
- [x] The bundled Trendee PDF can still be parsed by a smoke check, and the existing extraction behaviour (tables, reading order, OCR fallback) is preserved.
- [x] The dependency set is trimmed to the light stack and includes jieba, pytest, and python-dotenv.
- [x] The project's agent instructions point at the light spec instead of the archived heavy planning docs.
- [x] Archiving the heavy planning docs leaves no stale references in the app or README.
