# RAG Project Instructions

## Scope

本目录是万悉科技 AI 数据工程师笔试题第二题的独立项目，基线来自开源 ChatPDF（MIT License），入口为 `app.py`，核心逻辑在 `trendee_rag/` 包（`knowledge.py`、`embeddings.py`、`llm.py`、`writer.py`、`validation.py`、`artifacts.py`）。

- 验收依据：`../inputs/exam/万悉科技AI数据工程师笔试题.md`（任务二全部 bullet）
- 实现依据：`SPEC.md`（设计文档，不替代题目验收）
- 逐条映射与证据：`docs/requirements-traceability.md`
- 任务票：`../.scratch/rag-brand-writer/issues/`
- 输入 PDF：`../inputs/brand/Trendee品宣-公开版.pdf`
- 上游来源、commit、修改说明与 MIT 归属：`THIRD_PARTY_NOTICES.md`；许可条款：`LICENSE`
- 重型规划文档为本地过程档案，不随交付，也不参与实现。

## Technical Constraints

- PDF 是唯一事实来源；不得虚构公司人物、客户、收入、指标或案例。
- Embedding 默认使用本地 `sentence-transformers` `bge-m3`（`EMBEDDING_PROVIDER=local`，目录默认 `./data/bge-m3`）；需要 Docker 时可显式设置 `EMBEDDING_PROVIDER=ollama`（`http://127.0.0.1:11434`），两者均为 1024 维且检索逻辑一致。
- 写作生成必须使用明确的 LLM provider；没有配置时 fail closed。
- 引用必须映射到 `doc_name/pdf_page/page_label/section/excerpt`。
- `complete` 必须经过确定性引用检查和结构化 entailment 验证。
- 不提交 `.env`、`.venv`、`data/`、模型权重或真实密钥；日志不打印密钥和完整 prompt。
- 保留 `LICENSE` 和上游归属说明。

## Development Workflow

1. 先阅读 `SPEC.md` 和当前 ticket，再改代码。
2. 先补 characterization/unit tests，再修改解析、chunk、检索或写作逻辑。
3. 默认测试只运行 unit；真实 E2E 使用显式命令，不放入默认 pytest。
4. 任何未实现或未验证项必须记录为 `NOT RUN`，不能伪装为 PASS。

## Commands

```bash
.venv/Scripts/python.exe scripts/check.py
.venv/Scripts/python.exe -m streamlit run app.py
```

`scripts/check.py` runs `compileall`, `pytest`, and `scripts/check_secrets.py`. Run it before claiming completion or preparing a submission. Secret scan output must never include the matched value; `.env` is excluded.
