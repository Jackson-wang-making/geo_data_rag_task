"""Inject verifier failure modes through the real writer/parser path.

This drill does NOT call a remote LLM and does NOT need an API key. It uses:
  - the real local bge-m3 index over the bundled Trendee PDF,
  - the real deterministic citation validator,
  - the real `verify_entailment` parser and prompts,
  - a fake writer that returns the canonical article body,
  - a fake verifier transport that returns malformed JSON or raises.

The all-supported baseline must be `complete`; every injected failure must be
`partial` with the exact issue strings asserted below. Artifacts are written only
for the failure cases under `artifacts/verifier-drill/<timestamp>/<case>/`, so no
synthetic `complete` artifact can be mistaken for a real run.

Usage:
  .venv/Scripts/python.exe scripts/drill_verifier_failures.py \
      --model-path D:/ai_models/modelscope_cache/models/BAAI/bge-m3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from trendee_rag.artifacts import write_artifacts  # noqa: E402
from trendee_rag.embeddings import build_embedding_client  # noqa: E402
from trendee_rag.llm import LLMError, LLMResponse  # noqa: E402
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
from trendee_rag.validation import VERIFIER_SYSTEM_PROMPT, validate_citations, verify_entailment  # noqa: E402
from trendee_rag.writer import (  # noqa: E402
    SYSTEM_PROMPT,
    ArticleRequest,
    WriterDeps,
    _citation_manifest,
    generate_article,
)

DEFAULT_PDF = ROOT.parent / "inputs" / "brand" / "Trendee品宣-公开版.pdf"
DEFAULT_ARTICLE = ROOT / "examples" / "article.md"
TOPIC = "为什么中国出海品牌需要 GEO 优化"


class FakeWriterLLM:
    provider = "fake-drill"
    model_id = "fake-writer"

    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    def complete(self, messages, temperature, max_tokens):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        return LLMResponse(self.text, "stop", self.model_id)


class FakeVerifierLLM:
    provider = "fake-drill"
    model_id = "fake-verifier"

    def __init__(self, text: str | None = None, error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls: list[dict] = []

    def complete(self, messages, temperature, max_tokens):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        if self.error is not None:
            raise self.error
        assert self.text is not None
        return LLMResponse(self.text, "stop", self.model_id)


def _load_article_body(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    body = raw.split("\n\n---\n\n## 来源", 1)[0].rstrip()
    if "## 来源" in body:
        raise RuntimeError("failed to strip the source appendix from the example article")
    return body


def _all_supported(ids: list[str], fenced: bool = False) -> str:
    payload = json.dumps(
        {"claims": [{"id": claim_id, "verdict": "supported", "reason": "drill"} for claim_id in ids]},
        ensure_ascii=False,
    )
    return f"```json\n{payload}\n```" if fenced else payload


def _verifier_payload(ids: list[str], overrides: dict | None = None) -> str:
    overrides = overrides or {}
    claims = [
        {"id": claim_id, "verdict": overrides.get(claim_id, "supported"), "reason": "drill"}
        for claim_id in ids
    ]
    return json.dumps({"claims": claims}, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", default=r"D:/ai_models/modelscope_cache/models/BAAI/bge-m3")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--article", type=Path, default=DEFAULT_ARTICLE)
    parser.add_argument("--topic", default=TOPIC)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    failures: list[str] = []

    if not args.pdf.exists():
        print(f"PDF_NOT_FOUND {args.pdf}")
        return 2
    if not args.article.exists():
        print(f"ARTICLE_NOT_FOUND {args.article}")
        return 2

    article_body = _load_article_body(args.article)
    print(f"article_chars={len(article_body)} topic={args.topic}")

    embedder = build_embedding_client(
        provider="local",
        model="bge-m3",
        model_path=args.model_path,
        device=args.device,
    )
    embedder.health()

    store, report = ingest_pdf(args.pdf.read_bytes(), embedder, args.pdf.name)
    coverage = report.as_dict()
    print("coverage=" + json.dumps(coverage, ensure_ascii=False))
    if report.chunk_count != 43 or report.pages_without_chunks != [1, 8, 29]:
        print(
            f"UNEXPECTED_INDEX chunks={report.chunk_count} "
            f"pages_without_chunks={report.pages_without_chunks}"
        )
        return 2

    preview = search(store, embedder, args.topic, k=RETRIEVAL_TOP_K, min_dense=MIN_DENSE_SCORE)
    pages = [source["pdf_page"] for source in preview]
    print(f"retrieved={len(preview)} pages={pages}")
    if len(preview) != 10:
        print("UNEXPECTED_RETRIEVAL: expected 10 numbered sources; aborting before the drill.")
        return 2

    preflight = validate_citations(
        article_body,
        _citation_manifest(preview),
        [source["text"] for source in preview],
    )
    ids = [claim.id for claim in preflight.claims]
    print(
        f"preflight_passed={preflight.passed} claims={len(preflight.claims)} "
        f"ids={ids} issues={[issue.code for issue in preflight.issues]}"
    )
    if not preflight.passed or len(ids) != 10:
        print("PREFLIGHT_FAILED: the canonical article no longer matches this retrieval order.")
        for issue in preflight.issues:
            print(f"  [{issue.code}] {issue.claim_id}: {issue.detail}")
        return 2

    expected = {
        "malformed_json": ["校验器输出不是合法 JSON"],
        "missing_claim_id": [f"缺失 claim id：['{ids[-1]}']"],
        "duplicate_id": [f"重复 claim id：{ids[0]}"],
        "unknown_id": ["未知 claim id：c999"],
        "verdict_unsupported": [f"{ids[2]} 不被来源支持"],
        "verdict_uncertain": [f"{ids[2]} 的支持程度不确定"],
        "verifier_llm_error": ["校验器调用失败：drill verifier down"],
        "verifier_runtime_error": ["校验器异常：drill verifier boom"],
    }

    cases: list[tuple[str, str | None, Exception | None, list[str]]] = [
        ("baseline_supported", _all_supported(ids, fenced=True), None, []),
        ("malformed_json", "not json", None, expected["malformed_json"]),
        (
            "missing_claim_id",
            _verifier_payload(ids[:-1]),
            None,
            expected["missing_claim_id"],
        ),
        (
            "duplicate_id",
            _verifier_payload(ids + [ids[0]]),
            None,
            expected["duplicate_id"],
        ),
        (
            "unknown_id",
            _verifier_payload(ids + ["c999"]),
            None,
            expected["unknown_id"],
        ),
        (
            "verdict_unsupported",
            _verifier_payload(ids, {ids[2]: "unsupported"}),
            None,
            expected["verdict_unsupported"],
        ),
        (
            "verdict_uncertain",
            _verifier_payload(ids, {ids[2]: "uncertain"}),
            None,
            expected["verdict_uncertain"],
        ),
        (
            "verifier_llm_error",
            None,
            LLMError("LLM_UNAVAILABLE", "drill verifier down"),
            expected["verifier_llm_error"],
        ),
        (
            "verifier_runtime_error",
            None,
            RuntimeError("drill verifier boom"),
            expected["verifier_runtime_error"],
        ),
    ]

    expected_verifier_max = int(os.environ.get("VERIFIER_MAX_TOKENS", "4000"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    drill_base = ROOT / "artifacts" / "verifier-drill" / stamp

    for case_name, verifier_text, verifier_error, expected_issues in cases:
        writer = FakeWriterLLM(article_body)
        verifier_llm = FakeVerifierLLM(verifier_text, verifier_error)
        queries: list[str] = []

        def retrieve(query: str, _queries=queries):
            _queries.append(query)
            return search(store, embedder, query, k=RETRIEVAL_TOP_K, min_dense=MIN_DENSE_SCORE)

        deps = WriterDeps(
            retrieve=retrieve,
            llm=writer,
            embedding_model=store.embedding_model,
            embedding_provider="local",
            temperature=0.2,
            max_output_tokens=8000,
            max_context_chars=10000,
            retrieval_params={
                "top_k": RETRIEVAL_TOP_K,
                "min_dense_score": MIN_DENSE_SCORE,
                "rrf_k": RRF_K,
                "max_chunks_per_page": MAX_CHUNKS_PER_PAGE,
                "chunk_size_chars": CHUNK_SIZE,
                "chunk_overlap_chars": CHUNK_OVERLAP,
            },
            coverage=coverage,
            verifier=lambda claims, sources, _llm=verifier_llm: verify_entailment(
                claims, sources, _llm
            ),
        )
        request = ArticleRequest(topic=args.topic, content_type="blog")
        draft = generate_article(request, deps)

        problems: list[str] = []

        def check(condition: bool, message: str) -> None:
            if not condition:
                problems.append(message)

        is_baseline = case_name == "baseline_supported"
        # Unsupported/uncertain verdicts are well-formed verifier output; they
        # fail closed through issues/passed, not through the malformed flag.
        expected_malformed = (not is_baseline) and case_name not in (
            "verdict_unsupported",
            "verdict_uncertain",
        )
        entailment = draft.validation.get("entailment", {})
        deterministic = draft.validation.get("deterministic", {})

        check(queries == [args.topic], f"retrieve calls: {queries}")
        check(len(writer.calls) == 1, f"writer calls: {len(writer.calls)}")
        check(len(verifier_llm.calls) == 1, f"verifier calls: {len(verifier_llm.calls)}")
        check(
            draft.status == ("complete" if is_baseline else "partial"),
            f"status={draft.status}",
        )
        check(deterministic.get("passed") is True, f"deterministic passed={deterministic.get('passed')}")
        check(deterministic.get("claim_count") == 10, f"claim_count={deterministic.get('claim_count')}")
        check(draft.validation.get("repair_attempted") is False, "repair was attempted")
        check(entailment.get("ran") is True, "entailment did not run")
        check(
            entailment.get("passed") is is_baseline,
            f"entailment passed={entailment.get('passed')}",
        )
        check(
            entailment.get("malformed") is expected_malformed,
            f"entailment malformed={entailment.get('malformed')}",
        )
        check(entailment.get("issues") == expected_issues, f"issues={entailment.get('issues')}")
        check(draft.manual_review_items == expected_issues, f"manual_review={draft.manual_review_items}")
        check(draft.missing_sections == [], f"missing_sections={draft.missing_sections}")
        check(draft.finish_reason == "stop", f"finish_reason={draft.finish_reason}")
        check([item["pdf_page"] for item in draft.citations] == pages, "citation pages changed")
        check(
            all(item["citation_support_score"] is not None for item in draft.citations),
            "citation_support_score missing",
        )
        check(draft.evidence_manifest.get("status") == draft.status, "manifest status mismatch")
        check(draft.evidence_manifest.get("validation") == draft.validation, "manifest validation mismatch")
        check(draft.evidence_manifest.get("context_truncated") is False, "context truncated")
        check(draft.evidence_manifest.get("llm", {}).get("provider") == "fake-drill", "provider not fake-drill")

        if is_baseline:
            check(
                all(verdict == "supported" for verdict in entailment.get("verdicts", {}).values())
                and len(entailment.get("verdicts", {})) == 10,
                "baseline verdicts are not 10x supported",
            )
        else:
            check(entailment.get("verdicts") is not None, "verdicts missing")

        # Prove the real verifier prompt/payload path, not a stubbed EntailmentResult.
        if verifier_llm.calls:
            call = verifier_llm.calls[0]
            check(call["messages"][0]["content"] == VERIFIER_SYSTEM_PROMPT, "verifier system prompt changed")
            check(call["temperature"] == 0.0, f"verifier temperature={call['temperature']}")
            check(call["max_tokens"] == expected_verifier_max, f"verifier max_tokens={call['max_tokens']}")
            try:
                payload = json.loads(call["messages"][1]["content"])
                payload_ids = [item["id"] for item in payload["claims"]]
                check(payload_ids == ids, "verifier payload ids differ")
                for item in payload["claims"]:
                    expected_sources = [
                        {"n": n, "text": preview[n - 1]["text"][:800]} for n in item["citations"]
                    ]
                    check(item["sources"] == expected_sources, f"verifier sources differ for {item['id']}")
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                problems.append(f"verifier payload unreadable: {exc}")

        if writer.calls:
            user_content = writer.calls[0]["messages"][1]["content"]
            check(writer.calls[0]["messages"][0]["content"] == SYSTEM_PROMPT, "writer system prompt changed")
            check("<SOURCES>" in user_content, "writer context missing <SOURCES>")
            check(user_content.count("PDF page ") == len(preview), "writer source block count changed")

        artifact_note = "no artifact (baseline control)"
        if not is_baseline:
            bundle = write_artifacts(draft, request, base_dir=drill_base, run_id=case_name)
            evidence = json.loads((bundle.run_dir / "evidence.json").read_text(encoding="utf-8"))
            check(evidence.get("status") == "partial", "artifact status is not partial")
            check(
                evidence.get("validation", {}).get("entailment", {}).get("malformed")
                is expected_malformed,
                "artifact malformed mismatch",
            )
            check(evidence.get("manual_review_items") == expected_issues, "artifact manual_review mismatch")
            check(evidence.get("llm", {}).get("provider") == "fake-drill", "artifact provider mismatch")
            artifact_note = str(bundle.run_dir)

        if problems:
            failures.append(case_name)
            print(f"FAIL {case_name}: " + " | ".join(problems) + f" | {artifact_note}")
        else:
            verdict = entailment.get("verdicts", {})
            print(
                f"PASS {case_name}: status={draft.status} malformed={entailment.get('malformed')} "
                f"verdicts={len(verdict)} issues={entailment.get('issues')} | {artifact_note}"
            )

    print(f"drill_dir={drill_base}")
    if failures:
        print("FAILED_CASES=" + ",".join(failures))
        return 1
    print("ALL_CASES_PASSED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
