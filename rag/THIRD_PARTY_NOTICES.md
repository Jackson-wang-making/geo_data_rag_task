# Third-Party Notices

## ChatPDF

This project is based on ChatPDF's PDF parsing and RAG baseline:

- Repository: <https://github.com/Abdelrahman-Atef-Elsayed/ChatPDF>
- Baseline commit: `92a853a21a648ec38e117039d8751e797088eb53` (short: `92a853a`)
- License: MIT

The upstream source is not vendored in this deliverable. To inspect the exact baseline, check out the commit above from the upstream repository. The MIT license text retained with this project is in [LICENSE](LICENSE); it must remain with copies or substantial portions of the software.

### Changes in this project

The baseline's Streamlit shell, PDF extraction and retrieval ideas were adapted into a brand-content writing system: page-aware CJK chunking, Docker Ollama or local bge-m3 embeddings, dense + BM25 + RRF retrieval, a structured Chinese writer, deterministic citation checks with one repair, an LLM entailment verifier, fail-closed statuses, evidence artifacts, and download UI. Unused provider code and upstream demo media were removed. Details are in [README.md](README.md) and [SPEC.md](SPEC.md).
