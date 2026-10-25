"""Headless real-pipeline runner: PDF → embedding → retrieval → article → artifacts.

Examples (PowerShell):
  # 默认 EMBEDDING_PROVIDER=local；改用可选的 Docker 时再设置 ollama
  .venv\Scripts\python.exe scripts\run_e2e.py
  .venv\Scripts\python.exe scripts\run_e2e.py --retrieval-only --topic "GEO 方法论"

This script never prints the API key or the full prompt. Use it to reproduce the
example artifacts and to inspect retrieval before opening Streamlit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows consoles often default to GBK; the PDF contains bullets and other
# characters outside that code page. Keep the runner from crashing on output.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from trendee_rag.artifacts import write_artifacts  # noqa: E402
from trendee_rag.embeddings import EmbedError, build_embedding_client  # noqa: E402
from trendee_rag.llm import LLMError, build_llm_client  # noqa: E402
from trendee_rag.knowledge import (  # noqa: E402
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MAX_CHUNKS_PER_PAGE,
    MIN_DENSE_SCORE,
    RETRIEVAL_TOP_K,
    RRF_K,
    ingest_pdf,
    search,
)
from trendee_rag.writer import ArticleRequest, WriterDeps, generate_article  # noqa: E402

DEFAULT_PDF = ROOT.parent / "inputs" / "brand" / "Trendee品宣-公开版.pdf"


def _print_results(results: list[dict], limit: int = 5) -> None:
    for n, source in enumerate(results[:limit], start=1):
        snippet = source["text"].replace("\n", " ")[:160]
        print(
            f"  [{n}] p{source['pdf_page']} {source.get('section') or '-'} "
            f"dense={source.get('dense_score', 0):.4f} rrf={source.get('rrf_score', 0):.4f}\n"
            f"      {snippet}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="为什么中国出海品牌需要 GEO 优化")
    parser.add_argument(
        "--content-type", default="blog", choices=["blog", "faq", "brand_intro", "product_intro"]
    )
    parser.add_argument("--audience", default="中国出海品牌决策者")
    parser.add_argument("--tone", default="专业、克制、清晰")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--retrieval-only", action="store_true")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"PDF_NOT_FOUND {args.pdf}")
        return 2

    provider = os.environ.get("EMBEDDING_PROVIDER", "local")
    print(f"provider={provider} model={os.environ.get('EMBEDDING_MODEL', 'bge-m3')}")
    try:
        embedder = build_embedding_client()
        embedder.health()
    except EmbedError as exc:
        print(f"{exc.code}: {exc}")
        return 2

    print(f"ingesting {args.pdf.name} ...")
    try:
        store, report = ingest_pdf(args.pdf.read_bytes(), embedder, args.pdf.name)
    except (EmbedError, ValueError) as exc:
        print(f"INGEST_FAILED: {exc}")
        return 2

    coverage = report.as_dict()
    print("coverage=" + json.dumps(coverage, ensure_ascii=False))
    print(f"chunks={len(store.chunks)} dimension={store.dimension} model={store.embedding_model}")

    print(f"retrieval query: {args.topic}")
    try:
        results = search(store, embedder, args.topic, k=RETRIEVAL_TOP_K)
    except EmbedError as exc:
        print(f"{exc.code}: {exc}")
        return 2
    print(f"retrieved={len(results)}")
    _print_results(results)
    if args.retrieval_only:
        return 0

    print("generating article ...")
    try:
        llm = build_llm_client()
    except LLMError as exc:
        print(f"{exc.code}: {exc}")
        return 2

    deps = WriterDeps(
        retrieve=lambda query: search(store, embedder, query, k=RETRIEVAL_TOP_K),
        llm=llm,
        embedding_model=store.embedding_model,
        embedding_provider=provider,
        retrieval_params={
            "top_k": RETRIEVAL_TOP_K,
            "min_dense_score": MIN_DENSE_SCORE,
            "rrf_k": RRF_K,
            "max_chunks_per_page": MAX_CHUNKS_PER_PAGE,
            "chunk_size_chars": CHUNK_SIZE,
            "chunk_overlap_chars": CHUNK_OVERLAP,
        },
        coverage=coverage,
    )
    request = ArticleRequest(
        topic=args.topic,
        content_type=args.content_type,
        audience=args.audience,
        tone=args.tone,
    )
    draft = generate_article(request, deps)
    print(f"status={draft.status} finish_reason={draft.finish_reason}")
    if draft.error_code:
        print(f"error={draft.error_code}: {draft.error_message}")
    if draft.missing_sections:
        print("missing=" + json.dumps(draft.missing_sections, ensure_ascii=False))
    if draft.manual_review_items:
        print("manual_review=" + json.dumps(draft.manual_review_items, ensure_ascii=False))
    if draft.validation:
        deterministic = draft.validation.get("deterministic", {})
        entailment = draft.validation.get("entailment", {})
        print(
            f"deterministic={deterministic.get('passed')} claims={deterministic.get('claim_count')} "
            f"repair={draft.validation.get('repair_attempted')} "
            f"entailment={entailment.get('passed')} ran={entailment.get('ran')}"
        )

    if draft.status != "error":
        bundle = write_artifacts(draft, request)
        print(f"artifacts={bundle.run_dir}")
        print("article_preview=")
        print(draft.markdown[:4000])
    return 0 if draft.status in ("complete", "partial", "insufficient") else 1


if __name__ == "__main__":
    raise SystemExit(main())
