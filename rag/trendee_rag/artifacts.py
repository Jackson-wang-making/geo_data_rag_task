"""Write `article.md` and `evidence.json` for every generated draft."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .writer import ArticleDraft, ArticleRequest

ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "artifacts"


@dataclass
class ArtifactBundle:
    run_id: str
    run_dir: Path
    article_text: str
    evidence_text: str


def build_article_markdown(draft: ArticleDraft) -> str:
    """Append the source appendix required by the spec."""
    parts = [draft.markdown.rstrip(), "", "---", "", "## 来源", ""]
    if not draft.citations:
        parts.append("（无来源）")
    for n, citation in enumerate(draft.citations, start=1):
        page_label = str(citation.get("page_label", citation["pdf_page"]))
        label = f"[{n}] {citation['doc_name']} · PDF 第 {citation['pdf_page']} 页"
        if page_label != str(citation["pdf_page"]):
            label += f"（label {page_label}）"
        if citation.get("section"):
            label += f" · {citation['section']}"
        parts.extend([label, ""])
        excerpt = (citation.get("excerpt") or "").strip()
        if excerpt:
            parts.extend(["> " + excerpt.replace("\n", "\n> "), ""])
    return "\n".join(parts).rstrip() + "\n"


def build_evidence(
    draft: ArticleDraft,
    request: ArticleRequest,
    run_id: str,
    generated_at: str,
) -> dict:
    evidence = dict(draft.evidence_manifest)
    evidence.setdefault("topic", request.topic)
    evidence.setdefault("content_type", request.content_type)
    evidence["run_id"] = run_id
    evidence["generated_at"] = generated_at
    return evidence


def write_artifacts(
    draft: ArticleDraft,
    request: ArticleRequest,
    base_dir: Path | None = None,
    run_id: str | None = None,
) -> ArtifactBundle:
    """Persist both artifacts and return their contents for download buttons."""
    base = Path(base_dir) if base_dir is not None else ARTIFACTS_DIR
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    article_text = build_article_markdown(draft)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    evidence = build_evidence(draft, request, run_id, generated_at)
    evidence_text = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"

    (run_dir / "article.md").write_text(article_text, encoding="utf-8")
    (run_dir / "evidence.json").write_text(evidence_text, encoding="utf-8")
    return ArtifactBundle(
        run_id=run_id,
        run_dir=run_dir,
        article_text=article_text,
        evidence_text=evidence_text,
    )
