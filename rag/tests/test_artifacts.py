"""Artifact writing tests (no network or models)."""

import json

from trendee_rag.artifacts import write_artifacts
from trendee_rag.writer import ArticleDraft, ArticleRequest


def test_write_artifacts_appends_sources_and_serializes_evidence(tmp_path):
    draft = ArticleDraft(
        status="partial",
        markdown="# 标题\n\n正文。[1]",
        citations=[
            {
                "n": 1,
                "doc_name": "Trendee品宣-公开版.pdf",
                "pdf_page": 4,
                "page_label": "4",
                "section": "为什么选择LLM-原生GEO?",
                "type": "text",
                "excerpt": "生成式引擎正在改变用户获取信息的入口。",
                "dense_score": 0.81,
                "rrf_score": 0.032,
                "score": 0.032,
                "citation_support_score": 0.75,
            }
        ],
        evidence_manifest={"topic": "GEO", "validation": {"deterministic": {"passed": True}}},
    )
    bundle = write_artifacts(
        draft,
        ArticleRequest(topic="GEO"),
        base_dir=tmp_path,
        run_id="run-001",
    )

    article = (tmp_path / "run-001" / "article.md").read_text(encoding="utf-8")
    evidence = json.loads((tmp_path / "run-001" / "evidence.json").read_text(encoding="utf-8"))

    assert bundle.article_text == article
    assert "## 来源" in article
    assert "[1] Trendee品宣-公开版.pdf · PDF 第 4 页" in article
    assert "> 生成式引擎正在改变用户获取信息的入口。" in article
    assert evidence["run_id"] == "run-001"
    assert evidence["generated_at"]
    assert evidence["topic"] == "GEO"
    assert evidence["validation"]["deterministic"]["passed"] is True
    assert "api_key" not in bundle.evidence_text.lower()
