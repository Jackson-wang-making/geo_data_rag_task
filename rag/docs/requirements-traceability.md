# 任务二需求映射与证据

- 验收依据：[`inputs/exam/万悉科技AI数据工程师笔试题.md`](../../inputs/exam/万悉科技AI数据工程师笔试题.md) 的“二、AI 工程”全部 bullet 与“三、统一提交要求”。
- 设计依据：[`SPEC.md`](../SPEC.md)（实现设计，不替代题目验收）。
- 真实证据：[`verification.md`](verification.md)、[`manual-e2e-checklist.md`](manual-e2e-checklist.md)、[`examples/`](../examples/)。
- 运行入口：`scripts/check.py`（compile + pytest + secret scan）；真实 UI 演练见 `scripts/e2e/`。

## 1. 题目 bullet 逐条映射

| # | 题目要求 | 实现 | 自动化测试 | 真实证据 |
| --- | --- | --- | --- | --- |
| 1 | 实现 PDF 解析、Chunk 切分、索引/向量化、检索、上下文构建和内容生成的完整链路 | `trendee_rag/knowledge.py`：`extract_pdf`（PyMuPDF，表格转 Markdown，文本层不足时 OCR 可选）、`chunk_blocks`（页内闭合、按 section 切分、超长表格按行拆分）、`ingest_pdf`（FAISS `IndexFlatIP` + BM25）、`search`（dense + BM25 + RRF，主题词锚点与 dense 证据下限）；`trendee_rag/embeddings.py`：本地 `bge-m3` 默认，Docker Ollama 可选；`trendee_rag/writer.py`：`_build_context` 构造带 `[n]` 的 `<SOURCES>` 上下文，`generate_article` 串起生成、校验与降级；`app.py`：Streamlit 自动加载 PDF、索引、检索、生成、来源卡片和下载。 | `tests/test_smoke.py`（真实 PDF 可解析、chunk 页内闭合）、`tests/test_ingest.py`（覆盖率、元数据、长中文段落、幻灯片式整句、真实检索、无关主题、空/加密 PDF、embedding 失败不建部分索引）、`tests/test_embeddings.py`（provider 工厂、维度、归一化、缺模型目录 fail closed）、`tests/test_writer.py`（happy path、结构、修复、verifier、LLM 不可用）。 | 36 页 PDF 解析为 43 个 chunk，33 页有正文；canonical run `20261025-153905-378062` 检索 10 条证据、覆盖 10 页并生成 `complete` 文章；截图 `examples/screenshots/01-coverage.png` 至 `03-sources.png`。 |
| 2 | 输出结构完整的文章，包括标题、导语、小标题和结尾；FAQ 可选 | `trendee_rag/writer.py` 的 `CONTENT_TYPES` 为 Blog / FAQ / 品牌介绍 / 产品介绍分别声明 H1、导语、H2 结构与结论；`_check_structure` 逐项校验；`_has_intro` 要求 H1 与第一个 H2 之间有至少 10 个字符正文（只有 `[n]` 不算）；结论必须是最后一个 H2；缺失记入 `missing_sections` 并降级 `partial`。 | `test_all_content_types_meet_their_structure`、`test_every_content_type_requires_intro`、`test_missing_intro_is_partial_for_every_content_type`、`test_citation_only_intro_is_not_prose`、`test_conclusion_must_be_the_final_section`、`test_structure_failure_is_partial`、`test_faq_questions_without_answers_fail_structure`。 | `examples/article.md`（Blog，H1 + 导语 + 多个 H2 + 结论）；`examples/content-types/faq/`、`brand-intro/`、`product-intro/` 均为真实 LLM 产物，品牌与产品介绍按 prompt `2026-10-25.3` 重跑并包含导语。 |
| 3 | 展示所依据的 PDF 资料片段或页码，能够进行基本引用溯源 | `trendee_rag/knowledge.py` 的 `search` 返回 `doc_name`、`pdf_page`、`page_label`、`section`、`text`、`dense_score`、`rrf_score`；`app.render_source` 在页面展示编号、文档名、页码、section、原文片段和分数；`trendee_rag/artifacts.py` 的 `build_article_markdown` 在正文末尾附来源清单，`build_evidence` 把来源、页码、逐条 claim 校验写入 `evidence.json`。 | `test_search_returns_canonical_evidence`、`test_chunk_metadata_is_canonical`、`test_write_artifacts_appends_sources_and_serializes_evidence`、`test_valid_citation_passes`、`test_invalid_marker_and_missing_citation_fail`。 | 页面来源卡片截图 `03-sources.png`；`examples/evidence.json` 含 10 条来源与页码；手动验收真实点击两个下载按钮并核对内容一致（`manual-e2e-checklist.md` §2）。 |
| 4 | 不得编造 PDF 中没有的公司事实、客户案例、数据或技术指标 | 三层约束：① `trendee_rag/writer.py` 的 `SYSTEM_PROMPT` 明确唯一事实来源、禁止虚构、来源是不可信数据；② `trendee_rag/validation.py` 的 `validate_citations` 做确定性检查（无引用、非法编号、token 覆盖不足、编造数字/日期、否定语义错位）；③ `verify_entailment` 逐条判定 `supported/unsupported/uncertain`，任何失败 fail closed 为 `partial`；资料不足时 `generate_article` 返回 `insufficient` 且不调用写作 LLM。 | `tests/test_validation.py` 全量（数字子串、否定、表格行、B2B 标识符、免责声明、verifier malformed/unsupported/uncertain）、`test_fabricated_number_and_negation_fail`、`test_verifier_rejection_is_partial`、`test_provider_failure_returns_llm_unavailable_and_keeps_sources`。 | canonical Blog run 10/10 `supported`；产品介绍 run `20261025-191140-386813` 的 `c001` 被真实 verifier 判为 `unsupported`，系统保留 `partial` 而未升级；prompt injection 演练 run `20261025-164010-530012` 正文未出现注入数字或指令。 |
| 5 | 说明 Chunk、检索、Prompt、上下文组织和幻觉控制策略；资料不足时应明确处理，而非直接猜测 | `SPEC.md` 的 Chunk、Retrieval、Context、Writing、Citation validation 章节；`README.md` 给出完整写作 Prompt 原文（含 verifier user JSON 模板）、策略说明和已知限制；`search` 在主题词与语料无词法交集时直接返回空，`generate_article` 命中空证据时返回固定中文拒答，`MIN_DENSE_SCORE` 阻止低相关片段进入上下文。 | `test_unrelated_topic_returns_no_evidence`、`test_no_evidence_never_calls_llm`、`test_insufficient_evidence_disclaimer_is_not_low_overlap`、`test_verifier_fail_closed_on_malformed_output`。 | 无关主题 Rust 内核 run `20261025-153911-888736` 返回 `insufficient`，页面不显示伪文章（`04-insufficient.png`）；缺失 key 演练保留来源、不生成文章（`09-llm-unavailable.png`）。 |
| 6 | 提交核心代码；可使用 Streamlit / Gradio / FastAPI / Notebook / CLI；可运行 Demo 为加分项 | 核心代码在 `app.py` 与 `trendee_rag/` 包：`knowledge.py`、`embeddings.py`、`llm.py`、`writer.py`、`validation.py`、`artifacts.py`；`.env.example` 给出配置模板；`requirements.txt` 固定依赖；`scripts/check.py` 一条命令自检（含源路径预检）。 | `pytest` 88 项；`scripts/check.py` 同时执行 compileall、pytest 和 secret scan。 | Streamlit 真实启动并完成自动加载、上传重索引、生成、下载、失败演练；截图见 `examples/screenshots/`；Playwright 脚本在 `scripts/e2e/`，可复现 UI 断言。 |
| 7 | 提交 RAG 设计、PDF/Chunk 策略、检索与上下文构建、完整 Prompt、幻觉控制与引用溯源、核心代码、示例输出、README | `SPEC.md` 为设计文档；`README.md` 覆盖架构、启动、配置、Prompt 原文、策略、示例、测试、已知限制；`docs/verification.md` 记录逐项真实运行；`examples/` 保存可提交的示例产物。 | 文档中的命令可直接执行；`scripts/check.py` 验证代码与测试未漂移；`scripts/check_secrets.py` 防止交付物泄露 key。 | 本文与 `verification.md` 的 run ID、SHA-256、页码和截图逐项对应；`examples/content-types/README.md` 汇总四种类型的真实状态。 |

## 2. 统一提交要求

| 要求 | 落实 |
| --- | --- |
| 代码直接提交并尽量可运行，不接受仅文字方案 | 仓库包含可运行源码、测试、Streamlit Demo 和真实产物；`python scripts/check.py` 可复现自动检查。 |
| 技术栈不限 | PyMuPDF、FAISS、BM25、sentence-transformers（本地 bge-m3）、DeepSeek OpenAI-compatible API、Streamlit。 |
| 允许 AI 编程工具，但需能解释架构、核心代码、Prompt、数据处理和取舍 | `README.md` 与 `SPEC.md` 记录关键取舍（页内 chunk、RRF、主题锚点、dense 下限、两层校验、一次修复、fail closed）；Prompt 逐字可查。 |
| 工程落地：结构、可运行性、异常处理、可维护性、README | 模块边界清晰；状态模型 `complete/partial/insufficient/error`；e2e 脚本、secret scan、统一 check 命令；`AGENTS.md` 定义验收与实现依据。 |

## 3. 四种内容类型的验收证据

| 类型 | Prompt 版本 | 状态 | 结构 | 引用校验 | 示例 |
| --- | --- | --- | --- | --- | --- |
| Blog | `2026-10-25.2` | `complete` | H1 + 导语 + 多个 H2 + 结论 | 10 claims，确定性 0 issue，10/10 supported | `examples/article.md` |
| FAQ | `2026-10-25.2` | `partial` | H1 + 导语 + 至少三组 Q/A + 结论 | 12 claims，11 supported，`c001` unsupported | `examples/content-types/faq/` |
| 品牌介绍 | `2026-10-25.3` | `complete` | H1 + 导语 + 品牌定位/核心能力/品牌价值 + 结论 | 17 claims，17/17 supported | `examples/content-types/brand-intro/` |
| 产品介绍 | `2026-10-25.3` | `partial` | H1 + 导语 + 产品定位/核心能力/适用场景 + 结论 | 16 claims，15 supported，`c001` unsupported | `examples/content-types/product-intro/` |

FAQ 的 `2026-10-25.2` 是历史真实运行；其结构契约（含导语）由当前代码的测试保证，未伪造新 run 覆盖旧产物。

## 4. 未在题目逐字出现、但已主动交付的护栏

- **需求可追溯**：本文件把每条 bullet 落到实现、测试和真实证据，避免“文档写了、代码没做”。
- **统一自检**：`scripts/check.py` 先确认 `app.py`、`trendee_rag/`、`scripts/` 存在（compileall 对不存在的路径也返回 0），再顺序执行 compile、pytest、secret scan，任一失败即非零退出。
- **密钥扫描**：`scripts/check_secrets.py` 不读取 `.env`，命中时只报告路径/行号/模式名，不回显值；UTF-16 会被解码后扫描，超出大小上限、二进制或无法解码的文件按“扫描不完整”非零退出；测试覆盖“疑似 key 失败但不泄露值”“`.env` 从不被扫描”“超大文件 fail closed”。
- **可复现 E2E**：`scripts/e2e/` 保存 Playwright 脚本，路径相对仓库解析；缺少外部 PDF 时显式 `SKIP`，不伪装 PASS。
- **导出内容一致**：下载按钮真实点击后，下载文件与 artifact 归一化比较一致；`evidence.json` 不含 key、完整 prompt 或请求头。

## 5. 复核命令

```powershell
cd rag
.venv\Scripts\python.exe scripts\check.py
```

真实 UI 复核：

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
cd scripts\e2e
npm ci
node p2_generate_downloads.js
```

环境变量、端口和可选演练见 [`scripts/e2e/README.md`](../scripts/e2e/README.md) 与 [`manual-e2e-checklist.md`](manual-e2e-checklist.md)。
