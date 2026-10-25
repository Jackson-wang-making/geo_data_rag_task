"""Trendee 品牌内容 RAG 写作系统 — 检索 + 写作阶段。"""

import hashlib
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # .env 只存本地密钥，不进入版本库
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from trendee_rag.artifacts import write_artifacts
from trendee_rag.embeddings import EmbedError, build_embedding_client
from trendee_rag.knowledge import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MAX_CHUNKS_PER_PAGE,
    MIN_DENSE_SCORE,
    RETRIEVAL_TOP_K,
    RRF_K,
    ingest_pdf,
    search,
)
from trendee_rag.llm import build_llm_client
from trendee_rag.writer import CONTENT_TYPES, ArticleRequest, WriterDeps, generate_article

BUNDLED_PDF = ROOT.parent / "inputs" / "brand" / "Trendee品宣-公开版.pdf"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "local").strip().lower()
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_MODEL_PATH = os.environ.get(
    "EMBEDDING_MODEL_PATH", str(Path(__file__).resolve().parent / "data" / "bge-m3")
)
EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "cpu")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-flash")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")

st.set_page_config(page_title="Trendee 品牌内容 RAG 写作", page_icon="📝", layout="wide")


@st.cache_resource(show_spinner=False)
def get_embedder(
    provider: str, base_url: str, model: str, model_path: str, device: str
):
    return build_embedding_client(
        provider=provider, base_url=base_url, model=model, model_path=model_path, device=device
    )


@st.cache_resource(show_spinner=False)
def build_store(
    data: bytes, doc_name: str, provider: str, base_url: str, model: str, model_path: str, device: str
):
    """Parse, chunk, embed, and index. Cached per document for the server process."""
    return ingest_pdf(
        data, get_embedder(provider, base_url, model, model_path, device), doc_name
    )


class DeferredLLMClient:
    """Build the real LLM client on first completion, after retrieval.

    This keeps the missing-config path fail-closed while still returning the
    retrieved sources to the UI. Building eagerly in the click handler would
    skip retrieval entirely and hide the evidence panel.
    """

    provider = "openai_compatible"

    def __init__(self) -> None:
        self._client = None

    @property
    def model_id(self) -> str:
        return os.environ.get("LLM_MODEL", LLM_MODEL).strip() or "deepseek-flash"

    def complete(self, messages, temperature, max_tokens):
        if self._client is None:
            self._client = build_llm_client()
        return self._client.complete(messages, temperature, max_tokens)


def render_source(n: int, source: dict, expanded: bool = False) -> None:
    text = source.get("text") or source.get("excerpt") or ""
    section = source.get("section") or "（无 section）"
    label = f"[{n}] {source['doc_name']} · PDF 第 {source['pdf_page']} 页"
    if str(source.get("page_label", source["pdf_page"])) != str(source["pdf_page"]):
        label += f"（label {source['page_label']}）"
    label += f" · {section}"
    with st.expander(label, expanded=expanded):
        st.markdown(text[:1200] + ("…" if len(text) > 1200 else ""))
        scores = []
        for key, label_ in (("dense_score", "dense"), ("rrf_score", "RRF"), ("score", "final")):
            if source.get(key) is not None:
                scores.append(f"{label_}={source[key]:.4f}")
        if source.get("citation_support_score") is not None:
            scores.append(f"citation_support={source['citation_support_score']:.2f}")
        if scores:
            st.caption(" · ".join(scores))


def main() -> None:
    st.title("📝 Trendee 品牌内容 RAG 写作系统")
    st.caption("PDF → 页内 chunk → bge-m3 + FAISS/BM25 + RRF 检索 → DeepSeek 结构化文章。")

    with st.sidebar:
        st.subheader("文档")
        uploaded = st.file_uploader("上传 PDF（可选，上传后覆盖默认文档）", type=["pdf"])
        st.caption(f"默认文档：{BUNDLED_PDF.name}")
        st.divider()
        st.subheader("Embedding")
        st.caption(f"Provider：`{EMBEDDING_PROVIDER}`")
        st.caption(f"模型：`{EMBEDDING_MODEL}`")
        if EMBEDDING_PROVIDER == "local":
            st.caption(f"目录：`{EMBEDDING_MODEL_PATH}`")
            st.caption(f"设备：`{EMBEDDING_DEVICE}`")
        else:
            st.caption(f"服务：`{OLLAMA_BASE_URL}`")
        st.divider()
        st.subheader("写作 LLM")
        st.caption(f"模型：`{LLM_MODEL}`")
        st.caption(f"服务：`{LLM_BASE_URL or '未配置'}`")
        missing_llm = [
            name for name in ("LLM_API_KEY", "LLM_BASE_URL") if not os.environ.get(name)
        ]
        if missing_llm:
            st.warning(
                f"未配置 {' / '.join(missing_llm)}；生成会 fail closed（LLM_UNAVAILABLE）。"
            )

    if uploaded is not None:
        data, doc_name = uploaded.getvalue(), uploaded.name
    else:
        if not BUNDLED_PDF.exists():
            st.error(f"找不到默认 PDF：{BUNDLED_PDF}")
            return
        data, doc_name = BUNDLED_PDF.read_bytes(), BUNDLED_PDF.name

    # Drafts, evidence, and downloads must be scoped to the current PDF bytes.
    # Without this, uploading a replacement PDF would leave the previous
    # document's article visible under the new document's coverage metrics.
    doc_id = hashlib.sha256(doc_name.encode("utf-8") + b"\0" + data).hexdigest()[:12]

    try:
        with st.spinner(f"正在解析 {doc_name}、生成 embedding 并建立索引…"):
            store, report = build_store(
                data,
                doc_name,
                EMBEDDING_PROVIDER,
                OLLAMA_BASE_URL,
                EMBEDDING_MODEL,
                EMBEDDING_MODEL_PATH,
                EMBEDDING_DEVICE,
            )
    except EmbedError as exc:
        st.error(f"**{exc.code}** — {exc}")
        if EMBEDDING_PROVIDER == "local":
            st.info("未建立索引。请检查本地 bge-m3 模型目录与依赖后刷新页面重试。")
        else:
            st.info("未建立索引。启动 embedding 服务后刷新页面重试。")
        return
    except ValueError as exc:
        st.error(f"无法解析 PDF：{exc}")
        return
    except Exception as exc:
        st.error(f"索引失败：{exc}")
        return

    st.subheader("📊 数据覆盖")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("PDF 总页数", report.pages_total)
    c2.metric("有 chunk 的页", len(report.pages_with_chunks))
    c3.metric("无 chunk 的页", len(report.pages_without_chunks))
    c4.metric("OCR 不可用页", len(report.ocr_unavailable_pages))
    c5.metric("Chunk 数", report.chunk_count)

    details = [f"文档：`{report.doc_name}`", f"覆盖状态：`{report.coverage_status}`"]
    if report.ocr_pages:
        details.append(f"OCR 成功页：{report.ocr_pages}")
    if report.ocr_unavailable_pages:
        details.append(f"OCR 不可用页：{report.ocr_unavailable_pages}")
    st.caption(" · ".join(details))

    if report.pages_without_chunks:
        st.warning(f"以下页面没有可索引文本：{report.pages_without_chunks}。这些页不会出现在检索结果中。")
    if report.ocr_unavailable_pages:
        st.info(
            f"第 {report.ocr_unavailable_pages} 页需要 OCR，但本机未安装 Tesseract；"
            "这是已知的资料缺口，不应在文章中编造这些页的内容。"
        )

    if report.chunk_count == 0:
        st.error("没有提取到任何文本。请确认 PDF 不是整页扫描件，或安装 Tesseract 后重试。")
        return

    st.divider()
    st.subheader("✍️ 生成内容")
    topic = st.text_input("主题", placeholder="例如：为什么中国出海品牌需要进行 GEO 优化？")

    col_type, col_audience, col_tone = st.columns([1, 1, 1])
    with col_type:
        content_type = st.selectbox(
            "内容类型",
            list(CONTENT_TYPES),
            format_func=lambda key: CONTENT_TYPES[key]["label"],
        )
    with col_audience:
        audience = st.text_input("目标读者", value="中国出海品牌决策者")
    with col_tone:
        tone = st.text_input("语气", value="专业、克制、清晰")

    generate = st.button("生成文章", type="primary", disabled=not topic.strip())
    draft_key = f"{doc_id}|{topic.strip()}|{content_type}|{audience}|{tone}"

    if generate:
        st.session_state.article_artifact = None
        request = ArticleRequest(
            topic=topic.strip(), content_type=content_type, audience=audience, tone=tone
        )
        try:
            deps = WriterDeps(
                retrieve=lambda query: search(
                    store,
                    get_embedder(
                        EMBEDDING_PROVIDER,
                        OLLAMA_BASE_URL,
                        EMBEDDING_MODEL,
                        EMBEDDING_MODEL_PATH,
                        EMBEDDING_DEVICE,
                    ),
                    query,
                    k=RETRIEVAL_TOP_K,
                ),
                llm=DeferredLLMClient(),
                embedding_model=store.embedding_model,
                embedding_provider=EMBEDDING_PROVIDER,
                retrieval_params={
                    "top_k": RETRIEVAL_TOP_K,
                    "min_dense_score": MIN_DENSE_SCORE,
                    "rrf_k": RRF_K,
                    "max_chunks_per_page": MAX_CHUNKS_PER_PAGE,
                    "chunk_size_chars": CHUNK_SIZE,
                    "chunk_overlap_chars": CHUNK_OVERLAP,
                },
                coverage=report.as_dict(),
            )
            with st.spinner("正在基于检索证据生成文章…"):
                draft = generate_article(request, deps)
            st.session_state.article_draft = draft
            st.session_state.draft_key = draft_key
            if draft.status != "error":
                try:
                    bundle = write_artifacts(draft, request)
                    st.session_state.article_artifact = bundle
                    st.session_state.artifact_key = draft_key
                except (OSError, TypeError, ValueError) as exc:
                    st.warning(f"文章已生成，但写入产物失败：{exc}")
        except EmbedError as exc:
            st.session_state.article_draft = None
            st.error(f"**{exc.code}** — {exc}")
        except Exception as exc:  # keep the UI usable on unexpected writer/verifier bugs
            st.session_state.article_draft = None
            st.error(f"**GENERATION_FAILED** — {exc}")

    draft = st.session_state.get("article_draft")
    if draft is not None and st.session_state.get("draft_key") == draft_key:
        st.markdown("### 生成结果")
        if draft.status == "insufficient":
            st.warning(draft.markdown)
        elif draft.status == "error":
            st.error(f"**{draft.error_code}** — {draft.error_message}")
            st.info("未生成文章。已检索到的来源仍保留在下方，便于排查。")
        else:
            if draft.status == "complete":
                st.success("引用校验通过：确定性检查与逐条 entailment 均为 supported。")
            else:
                st.warning("文章状态为 partial：存在缺失结构、未通过校验或需要人工复核的内容。")
            deterministic = draft.validation.get("deterministic", {})
            if draft.validation.get("repair_attempted"):
                st.caption("首次生成未通过引用校验，已自动修复一次。")
            if deterministic and not deterministic.get("passed", True):
                st.warning(
                    f"确定性引用校验发现 {len(deterministic.get('issues', []))} 个问题。"
                )
            entailment = draft.validation.get("entailment", {})
            if entailment.get("ran") and not entailment.get("passed"):
                st.warning("entailment 校验未通过：存在 unsupported、uncertain 或校验器输出异常。")
            if draft.missing_sections:
                st.warning("缺失或异常：" + "；".join(draft.missing_sections))
            if draft.markdown:
                st.markdown(draft.markdown)
            if draft.manual_review_items:
                with st.expander("需要人工复核", expanded=draft.status != "complete"):
                    for item in draft.manual_review_items:
                        st.write(f"- {item}")

        if draft.citations:
            st.markdown("#### 来源")
            for n, source in enumerate(draft.citations, start=1):
                render_source(n, source, expanded=n == 1)

        artifact = st.session_state.get("article_artifact")
        if artifact is not None and st.session_state.get("artifact_key") == draft_key:
            st.markdown("#### 下载本次产物")
            col_md, col_json = st.columns(2)
            col_md.download_button(
                "下载 article.md",
                artifact.article_text,
                file_name="article.md",
                mime="text/markdown",
                use_container_width=True,
            )
            col_json.download_button(
                "下载 evidence.json",
                artifact.evidence_text,
                file_name="evidence.json",
                mime="application/json",
                use_container_width=True,
            )
            st.caption(f"已写入：`{artifact.run_dir}`")

    st.divider()
    with st.expander("🔎 检索证据预览（不生成文章）"):
        evidence_key = f"{doc_id}|{topic.strip()}"
        if st.button("检索证据", disabled=not topic.strip()):
            try:
                with st.spinner("检索中…"):
                    st.session_state.evidence = search(
                        store,
                        get_embedder(
                            EMBEDDING_PROVIDER,
                            OLLAMA_BASE_URL,
                            EMBEDDING_MODEL,
                            EMBEDDING_MODEL_PATH,
                            EMBEDDING_DEVICE,
                        ),
                        topic.strip(),
                        k=RETRIEVAL_TOP_K,
                    )
                st.session_state.evidence_key = evidence_key
            except EmbedError as exc:
                st.error(f"**{exc.code}** — {exc}")

        evidence = st.session_state.get("evidence")
        if st.session_state.get("evidence_key") == evidence_key and evidence is not None:
            if not evidence:
                st.warning(
                    "没有检索到证据：主题词没有在 PDF 中出现，或候选未超过相关度地板"
                    f"（dense ≥ {MIN_DENSE_SCORE:.2f}）。请换一个主题或确认 PDF 是否覆盖该内容。"
                )
            else:
                st.success(f"检索到 {len(evidence)} 条证据，覆盖 {len({r['pdf_page'] for r in evidence})} 个页面。")
                for n, source in enumerate(evidence, start=1):
                    render_source(n, source, expanded=n == 1)


main()
