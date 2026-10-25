# Lightweight RAG Brand Writing System — Spec

- Status: ready-for-agent
- Date: 2026-10-25
- Revision: 2026-10-25.3（任务二验收项逐条映射 + 全内容类型导语 + secret/check 护栏 + E2E 可复现）
- Tracker: Local Markdown (`.scratch/rag-brand-writer/spec.md`)
- Canonical copy: `rag/SPEC.md`
- Supersedes: the earlier heavy RALPLAN spec (20 AC); its local-only archive is `.omx/archive/rag-planning/spec.md` and is not part of the deliverable
- Baseline: ChatPDF (MIT License)

## Problem Statement

考生需要在今晚提交万悉科技 AI 数据工程师笔试第二题。题目要求基于 Trendee 品宣 PDF 构建一个 RAG 写作系统，生成官网 Blog、FAQ、品牌介绍或产品介绍；每条事实必须能追溯到 PDF 页码和片段；资料不足时必须明确说明，不得编造。

现有 `rag/` 是 ChatPDF 的 PDF 问答应用，不是写作系统；已有的 20 条 AC 重型规划超出今晚可交付范围。面试官需要能在一台新机器上按 README 跑起来，输入示例主题，看到结构完整的中文文章、可核对的来源页码，以及资料不足时的拒答行为。

## Solution

在现有 `rag/` 项目内做一个轻量、可解释的 Streamlit 应用：

1. 默认加载仓库内的 Trendee PDF，也允许上传覆盖。
2. PDF 解析后按页边界做中文友好的 chunk（目标 700 字，overlap 100 字）。
3. 通过本地 sentence-transformers `bge-m3`（默认）或显式启用的 Docker Ollama `bge-m3` 生成 1024 维归一化向量，建立 FAISS dense 索引；同时用 jieba 分词建立 BM25 稀疏索引。
4. 用户输入主题并选择内容类型后，用 dense + BM25 + RRF 检索 top-k 证据，构建带 `[n]` 编号的上下文。
5. 调用 DeepSeek（OpenAI-compatible）生成结构化中文文章。
6. 生成后做两层校验：确定性引用检查 + 一次 LLM entailment 校验；失败则修复一次或降级为 `partial` / `insufficient`，绝不把无依据内容标成 `complete`。
7. 页面展示文章正文、来源卡片（文档名 / PDF 页码 / section / 片段 / 分数）、覆盖率警告，并支持下载 `article.md` 与 `evidence.json`。
8. 仓库内附真实示例产物与 README，供不运行代码的面试官直接查看。
9. 四种内容类型统一满足题目“标题、导语、小标题、结尾”的结构要求；`SPEC.md` 是实现设计，题目原文是验收基准。
10. 仓库提供题目要求逐条映射、secret scan、统一 `scripts/check.py` 和可复现 Playwright 脚本，交付前可一条命令自检。

## User Stories

1. 作为考生，我想用一条命令启动 Streamlit 应用，以便在提交前快速自测并截图。
2. 作为面试官，我想打开应用就看到 Trendee PDF 已被自动加载并完成索引，以便不用手动上传就能验证效果。
3. 作为面试官，我想仍然可以上传自己的 PDF 覆盖默认文档，以便验证系统不是硬编码单一样例。
4. 作为考生，我想在界面上看到 PDF 总页数、有效页数、chunk 数和缺失/OCR 不可用页，以便在面试时解释数据覆盖质量。
5. 作为面试官，我想看到 embedding 服务不可用时的可操作错误（例如检查本地模型目录，或启动哪个容器），以便快速恢复环境。
6. 作为考生，我想选择 Blog / FAQ / 品牌介绍 / 产品介绍四种内容类型，以便覆盖题目要求的所有输出形态。
7. 作为考生，我想输入任意中文主题，以便生成题目示例之外的文章。
8. 作为面试官，我想输入“为什么中国出海品牌需要进行 GEO 优化？”并选择 Blog，以便复现题目示例。
9. 作为面试官，我想看到每种内容类型都包含标题、导语、对应的小标题和结论，以便确认输出是结构化长文而不是问答片段。
10. 作为面试官，我想在 FAQ 类型下看到至少三组 Q/A，以便确认模板切换有效。
11. 作为面试官，我想看到每个事实性段落带 `[n]` 引用，以便确认事实可追溯。
12. 作为面试官，我想查看来源卡片，看到 `[n]` 对应的文档名、PDF 页码、section、原文片段和相关度，以便核对文章没有编造。
13. 作为面试官，我想下载 `article.md`，以便离线查看文章和来源附录。
14. 作为面试官，我想下载 `evidence.json`，以便查看本次生成的模型、参数、检索结果、引用校验状态和覆盖率。
15. 作为考生，我想在检索不到足够证据时不调用 LLM，并看到“现有资料不足以回答该主题”的明确提示，以便演示 fail-closed。
16. 作为考生，我想在只有部分章节有证据时看到 `partial` 状态和缺失内容列表，以便演示“不猜测”的处理方式。
17. 作为面试官，我想在 LLM 不可用或鉴权失败时看到错误和已检索来源，而不是一篇伪造文章，以便确认系统没有降级成假生成。
18. 作为面试官，我想看到非法 `[n]`、无引用事实段落、数字/日期在来源中不存在等情况的处理结果，以便确认引用校验不是摆设。
19. 作为面试官，我想看到 entailment 校验把不支持/不确定的句子标出来，以便确认系统能识别“编号合法但内容不支持”的假引用。
20. 作为考生，我想把 PDF 中的指令性文本当作数据而不是系统指令，以便演示提示注入防护。
21. 作为考生，我想看到中文长段落不会被切坏或丢弃，以便确认 chunker 对中文有效。
22. 作为面试官，我想用中文关键词检索到相关段落，以便确认 BM25 分词对中文有效。
23. 作为面试官，我想看到检索结果覆盖多个页面/section，以便确认文章不是只基于一页内容。
24. 作为面试官，我想在 PDF 加密或没有可提取文本时看到明确错误，以便知道输入有问题。
25. 作为面试官，我想看到 OCR 不可用的页码被明确列出，而不是被静默忽略，以便了解资料缺口。
26. 作为面试官，我想看到文章因 token 上限被截断时不被标记为成功，以便确认状态可信。
27. 作为考生，我想在 README 中看到完整写作 Prompt、架构说明、chunk/检索/校验策略和已知限制，以便面试时逐项解释。
28. 作为面试官，我想在 README 中看到 ChatPDF 的 MIT 归属和本项目修改点，以便确认许可证合规。
29. 作为面试官，我想在仓库里直接看到一组真实示例 `article.md`、`evidence.json` 和截图，以便不运行代码也能评估输出质量。
30. 作为考生，我想让所有密钥只存在本地 `.env`，以便安全提交代码。
31. 作为维护者，我想让核心链路只保留少量模块和清晰接口，以便面试时逐层讲解。
32. 作为考生，我想在一次生成失败后不需要重启整个应用就能重试，以便演示过程稳定。
33. 作为面试官，我想看到题目“二、AI 工程”的每一条要求都映射到代码、测试和真实证据，以便快速核对是否有遗漏。
34. 作为维护者，我想让四种内容类型都强制包含导语，以便不会因为只抽检 Blog 而漏掉品牌/产品结构。
35. 作为考生，我想在提交前运行一条命令完成编译、测试和 secret scan，以便不会把 key 或坏代码交出去。

## Implementation Decisions

### Scope and architecture

- 单 PDF、单用户、本地 Streamlit；不做鉴权、多租户、多 PDF 知识库。
- 复用基线的 PDF 解析能力（PyMuPDF、表格、阅读顺序、OCR 回退），但不复用其按英文单词计长的 chunker。
- 产品形态从“PDF 问答”改为“主题 + 内容类型 → 结构化文章”。
- 内容类型固定为 `blog | faq | brand_intro | product_intro`；输出语言为中文。
- 模块保持少而清晰：PDF 解析、chunking、embedding client、检索 store、writer pipeline、LLM adapter、Streamlit UI。

### Ingestion

- 每次导入产出 `IngestReport`：`pages_total`、`pages_with_chunks`、`pages_without_chunks`、`ocr_pages`、`ocr_unavailable_pages`、`chunk_count`、`coverage_status`。
- Chunker 必须页内闭合：任何 chunk 不得跨页。
- 中文长度统一用 `cjk_len()`：CJK 字符按 1 计，拉丁词按 1 计；`_pack`、最小长度、heading flush、表格切分都使用同一函数。
- 默认 `CHUNK_SIZE_CHARS=700`（允许 400–900），`CHUNK_OVERLAP_CHARS=100`（允许 0–150）。
- heading 与其后第一段正文同 chunk；超长中文段落按字符窗口切分，不得因无空格被当作碎片丢弃。
- 表格按行切分并在每片重复表头；空文本、纯页码、重复页眉页脚不进入索引。
- Chunk 规范字段：`chunk_id`、`doc_name`、`pdf_page`、`page_label`、`section`、`type`、`text`、`index_text`、`char_count`。
- `index_text` 为 section + 正文（section 已在正文开头时不重复）。
- 同一文档内按 `(doc_name, pdf_page, hash(normalized_text))` 去重。

### Embedding

- 定义 `EmbeddingClient` 协议：`model_id`、`dimension`、`health()`、`encode(texts) -> float32 ndarray`。
- 默认实现为 `SentenceTransformerEmbeddingClient`（`EMBEDDING_PROVIDER=local`）：加载 `BAAI/bge-m3`，目录默认 `rag/data/bge-m3`，输出 1024 维归一化向量；相对 `EMBEDDING_MODEL_PATH` 按项目根目录解析。它不会静默替换成不同模型；canonical Blog 与 FAQ 真实运行使用这条本地路径，其他历史 run 显式使用 Docker Ollama。
- 可选实现为 `OllamaEmbeddingClient`：`POST {OLLAMA_BASE_URL}/api/embed`，模型 `bge-m3`，批量默认 8，超时 120 秒；仅在显式设置 `EMBEDDING_PROVIDER=ollama` 时启用。
- 校验响应数量、维度（1024）、是否 finite；索引前执行 L2 normalize。
- 索引前必须通过 `health()`；失败返回 `EMBED_UNAVAILABLE` / `EMBED_MODEL_MISSING`，并给出可执行提示。
- Store 元数据记录 `embedding_model`、`dimension`、`chunk_count`；`evidence.json` 额外记录 `embedding_provider`。
- 默认本地路径需要 `sentence-transformers` / `torch`，二者已写入 `requirements.txt`；可选 Docker 路径不依赖它们。应用对两种 provider 都保持 fail closed，不会静默改写 provider。

### Index and retrieval

- 索引只保存在内存中，每次导入重建；不做索引持久化与版本迁移（36 页规模足够小）。
- Dense：FAISS `IndexFlatIP`，向量已归一化。
- Sparse：`BM25Okapi`；含 CJK 的文本用 `jieba.lcut()` 分词、小写、去标点/停用词；非 CJK 保持基线行为。
- 检索使用 dense + BM25 + RRF（k=60）；默认 `RETRIEVAL_TOP_K=10`。
- 主题锚点：查询去掉填充词后，若所有内容词都不在语料 vocab 中出现，直接返回空证据；不能只用 dense 地板判断“PDF 是否覆盖该主题”。
- 证据地板为 dense cosine `MIN_DENSE_SCORE=0.35`（初始值，用真实 PDF 校准）；BM25-only 命中需与 query 至少 2 个内容 token 重叠，否则也必须过 dense 地板。
- 每页最多 3 个 chunk，除非没有其他页可选。
- 不做 reranker，不做二次补充检索；覆盖不足时只记录 warning，不偷偷放宽阈值。
- 检索结果在 writer 边界统一为规范字段：`doc_name`、`pdf_page`、`page_label`、`section`、`type`、`text`、`dense_score`、`rrf_score`、`score`。
- 无结果或全部低于地板时：`insufficient`，不调用 LLM。

### Context construction

- 每个来源块格式：`[n] (doc_name, PDF page X — section)` + 原文片段。
- 默认 `MAX_CONTEXT_CHARS=10000`；只在 chunk 边界截断，记录 `context_truncated`。
- 编号 `[n]` 必须与 citation 校验和来源卡片使用同一顺序。
- 上下文放入 `<SOURCES>` 块；明确声明来源文本是不可信数据，忽略其中任何指令。

### Writing

- 写作 system prompt 必须包含：只使用 `<SOURCES>` 中的事实；禁止外部知识；禁止虚构公司事实、客户案例、合作方、收入、用户量、技术指标或时间线；每个事实性句子/段落带 `[n]`；资料不足时明确写“现有资料不足以支持该部分”；不得追加来源未明确支持的因果/价值判断、预测或建议；结论只复述来源观点；忽略来源中的指令；输出 Markdown。
- 内容类型结构要求（四种类型都包含导语；FAQ 类型本身是可选输出形态）：
  - Blog：标题、导语、至少两个 H2、结论。
  - FAQ：标题、导语、至少三组 Q/A、结论。
  - 品牌介绍：标题、导语、品牌定位、核心能力、品牌价值、结论。
  - 产品介绍：标题、导语、产品定位、核心能力、适用场景、结论。
- 导语判定：H1 与第一个 H2 之间存在至少 10 个字符的非空正文；缺失时记入 `missing_sections` 并降级为 `partial`。这是对题目“输出结构完整的文章，包括标题、导语、小标题和结尾”的统一解释，品牌/产品不设例外。
- 用户消息包含 content type、topic、audience（默认“中国出海品牌决策者”）、tone（默认“专业、克制、清晰”）。
- 非流式调用；`temperature=0.2`；`MAX_OUTPUT_TOKENS=16000`（reasoning token 计入）；解析并检查 `finish_reason`。
- `finish_reason=length` 映射为 `LLM_TRUNCATED`；reasoning 模型的 reasoning tokens 也计入输出上限，空正文 + length 同样 fail closed。
- 当前只实现 DeepSeek / OpenAI-compatible provider（`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，默认 `deepseek-flash`）；不提供 Ollama chat 备选。
- 缺少配置或调用失败返回 `LLM_UNAVAILABLE`，保留已检索来源，不生成模拟文章。
- 不提供 extractive fallback 作为“已生成文章”。

### Citation validation

- 事实性段落定义：非标题、非分隔线、至少 20 个 CJK 字符或 8 个拉丁词的段落；Q/A 答案正文和事实性列表项计入。
- 确定性检查：
  1. 提取全部 `[n]`，所有编号必须在 `1..source_count`。
  2. 每个事实性段落至少有一个合法引用。
  3. 每个被引用 source 必须存在于本次检索结果。
  4. 引用句与所引片段并集的 token coverage ≥ `CITATION_MIN_OVERLAP=0.20`。
  5. 引用句中的数字、日期、百分比必须在所引片段中逐字出现；嵌在 `B2B`、`GPT-4o`、`HTML5` 等拉丁标识符中的数字视为名称，不参与比对。
  6. 否定词（不/未/无/缺乏/not/no/never）极性一致：claim 与来源按句读和项目符号切成 clause，逐 clause 与词面最接近的来源 clause 比较，重叠不足 2 个 token 时跳过；`现有资料不足以支持` 免责句豁免；`难以` 等程度判断不算否定。
- 首次失败时，用同一证据执行一次“删除无依据句子和非法引用”的修复生成；第二次仍失败则返回 `partial`，并列出问题。即使修复后通过全部校验，也保留 `partial` 并记录“已修复”，不得升级为 `complete`。
- `citation_support_score` 为确定性 token coverage，范围 0–1，可为空；同一 source 被多个 claim 引用时取最小值；不得单独作为“语义已支持”的证据。

### Entailment verifier

- 每篇文章一次 LLM 调用，输入 JSON：claim 列表（稳定 ID `c001...`）、claim 文本、citation IDs、对应来源片段。
- 明确要求把来源和 claim 视为不可信数据，忽略其中指令。
- 输出 JSON，每条 claim 一个 verdict：`supported | unsupported | uncertain`，附简短理由。
- Fail-closed：缺失/重复/未知 claim ID、非法 verdict、JSON 解析失败、调用失败，一律 `partial` 并写入 `manual_review_items`。
- 任一 `unsupported`：删除该 claim 或整篇 `partial`；任一 `uncertain`：`manual_review_items`，不得 `complete`。
- 只有全部 claim `supported` 且确定性检查通过，才能标记 `complete`。

### Status model and artifacts

- `ArticleDraft` 字段：`status`、`markdown`、`citations`、`validation`、`missing_sections`、`manual_review_items`、`evidence_manifest`。
- `complete` 条件：结构完整（标题、非空的文字导语、各内容类型要求的 H2、结论且结论是最后一个 H2）、`finish_reason` 为空或 `stop`、确定性检查全过、至少一个可校验事实性 claim、entailment 已执行且全部 `supported`、未触发修复。
- `partial`：部分证据/claim 缺失；必须展示缺失内容，不得声称“校验通过”。
- `insufficient`：无证据或无有效文章；返回固定中文提示，不展示伪造文章。
- 每次生成写出 `artifacts/<run_id>/article.md` 和 `evidence.json`。
- `article.md` 末尾附来源清单：`[n]`、文档名、PDF page、page label、section、excerpt。
- `evidence.json` 必须包含：topic、content_type、embedding model、retrieval 参数、sources、coverage、LLM provider/model、temperature、max_output_tokens、prompt_version、context_truncated、finish_reason、status、validation、missing_sections、manual_review_items。
- 仓库提交一组真实示例产物（`examples/article.md`、`examples/evidence.json`）和 2–3 张运行截图。

### UI

- 单页 Streamlit：顶部状态/覆盖率横幅、主题输入、内容类型选择、可选 audience/tone、Generate 按钮、文章区、来源区、下载按钮。
- 首次打开自动加载仓库内 Trendee PDF；上传新 PDF 时重新索引并覆盖当前索引。
- 状态机：`EMPTY → INDEXING → READY → GENERATING → COMPLETE | PARTIAL | INSUFFICIENT`；任何状态可进入 `ERROR`。
- 索引/生成期间禁用重复提交；错误信息必须带可执行 next action。
- 来源卡片显示 `[n]`、文档名、PDF page、section、excerpt、score。
- 文章与来源分离展示；`PARTIAL` 显示缺失标签；`INSUFFICIENT` 不显示文章区。
- 不做聊天历史、PDF 导出、多 PDF 管理。

### Configuration and security

| 变量 | 默认 | 说明 |
|---|---|---|
| `EMBEDDING_PROVIDER` | `local` | `local`（默认）或 `ollama`（可选） |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Docker Ollama（仅 `ollama`） |
| `EMBEDDING_MODEL` | `bge-m3` | 必须与索引元数据一致 |
| `EMBEDDING_MODEL_PATH` | `./data/bge-m3` | 本地模型目录（`local`；相对路径按项目根解析） |
| `EMBEDDING_DEVICE` | `cpu` | 本地推理设备（`local`） |
| `EMBEDDING_BATCH_SIZE` | `8` | 批量大小 |
| `EMBEDDING_TIMEOUT` | `120` | 秒 |
| `LLM_PROVIDER` | `openai_compatible` | 当前只支持 OpenAI-compatible |
| `LLM_BASE_URL` | 空 | DeepSeek: `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | 空 | 只放本地 `.env` |
| `LLM_MODEL` | `deepseek-flash` | 生成模型 |
| `LLM_TEMPERATURE` | `0.2` | 写作温度 |
| `MAX_OUTPUT_TOKENS` | `16000` | 输出上限；reasoning token 也计入 |
| `VERIFIER_MAX_TOKENS` | `4000` | entailment 校验器上限 |
| `LLM_TIMEOUT` | `300` | 单次请求超时（秒） |
| `CHUNK_SIZE_CHARS` | `700` | 中文 chunk 预算 |
| `CHUNK_OVERLAP_CHARS` | `100` | 字符 overlap |
| `RETRIEVAL_TOP_K` | `10` | 检索条数 |
| `MIN_DENSE_SCORE` | `0.35` | 证据地板 |
| `MAX_CONTEXT_CHARS` | `10000` | 上下文预算 |
| `CITATION_MIN_OVERLAP` | `0.20` | 引用最小 token 覆盖率 |

- `.env` 不提交；日志不打印 API key、完整 prompt 或未脱敏敏感信息。
- `scripts/check_secrets.py` 扫描工作区文本文件，跳过 `.env`、`.venv`、`data/`、`artifacts/`、`node_modules/` 等目录；命中时只输出文件、行号和模式名，绝不输出匹配值。交付前必须通过。
- Playwright 脚本不打印 `process.env`、请求头或 `.env`；截图、下载和日志只落在 ignored 的 `scripts/e2e/out/`。
- README 说明所有密钥的配置方式与 provider 信任边界。

### Documentation and repository hygiene

- 重型 `docs/planning/` 已移到本地过程档案 `.omx/archive/rag-planning/`（不随交付），不删除；本 Spec 是实现设计，题目原文是验收基准。
- `docs/requirements-traceability.md` 把题目“二、AI 工程”的每条 bullet 映射到实现、测试、真实证据；需求或实现变化时先更新该表，再改本 Spec。
- `rag/AGENTS.md` 同时指向题目原文、`SPEC.md` 和 `docs/requirements-traceability.md`，避免后续会话只读 Spec 而漏掉题目口径。
- `scripts/check.py` 串行运行 `compileall`、`pytest` 和 `scripts/check_secrets.py`；`check_secrets.py` 从不读取 `.env`，只报告路径/行号/模式名，不打印匹配值。
- `scripts/e2e/` 收纳 Playwright 脚本，默认输出到 `scripts/e2e/out/`（gitignored）；选中截图再复制到 `examples/screenshots/`。脚本支持 `E2E_OTHER_PDF`、`E2E_EMPTY_MODEL_DIR`、`E2E_EMBEDDING_PROVIDER` 等覆盖。
- 删除未使用的 provider 分支、demo 视频和与写作无关的上游 UI 文案。
- 保留 `LICENSE`；README 与 `THIRD_PARTY_NOTICES.md` 注明 ChatPDF 来源、上游 commit 与本项目修改点。
- README 用中文重写，包含：架构图、启动步骤、本地 bge-m3（可选 Docker Ollama）/DeepSeek 配置、完整写作 Prompt（逐字，含 verifier user JSON 模板）、chunk/检索/上下文/引用校验策略、示例输入输出、已知限制、`scripts/check.py` 与测试命令。

## Testing Decisions

- 好测试只验证外部行为，不验证内部实现；网络和模型依赖通过 fake 注入，测试必须确定性、无外网。
- 采用两个 pipeline seam（现有代码没有测试，属于新建 seam）：
  1. **Ingestion seam**：`ingest_pdf(data, embedder) -> (store, IngestReport)`。用 fake embedder 返回确定性向量。覆盖：chunk 不跨页、中文长段落不被丢弃、chunk 元数据完整、重复文本去重、空/加密 PDF 错误、覆盖率报告正确列出缺失页。
  2. **Writing seam**：`generate_article(request, deps) -> ArticleDraft`。`deps` 注入 store/retriever、LLM、verifier。覆盖：无证据时 `insufficient` 且不调用 LLM；合法引用时 `complete`；非法 `[n]` 修复一次后 `partial`；无引用事实段落 → `partial`；编造数字 → `partial`；verifier 返回 malformed/unsupported → `partial`；LLM 不可用 → 错误且无文章；`finish_reason=length` → `partial`。
- 纯函数（`cjk_len`、CJK tokenizer、citation marker 解析）只在上述 seam 测试覆盖成本过高时单独测试；优先通过 pipeline seam 验证行为。
- 结构契约测试：四种内容类型都必须在 `CONTENT_TYPES` 中声明导语；对每种类型删除导语后必须返回 `partial` 且 `missing_sections` 包含“导语”。测试保护题目口径，而不是只保护当前 fixture。
- secret scan 测试：临时目录中的 likely key 必须让 `check_secrets.py` 返回非零，且 stdout/stderr 不出现匹配值；`.env` 必须被跳过。
- 真实端到端为手动/脚本化验证，不放入默认 pytest：真实 PDF + 本地 bge-m3（默认）或 Docker Ollama + DeepSeek，生成题目示例文章，检查结构、引用、来源和下载，然后把产物复制到 `examples/`。
- 不做 Streamlit AppTest；UI 用 `scripts/e2e/` 下的 Playwright/人工 checklist 验证。
- 默认 pytest 套件使用 fake embedder / fake LLM，不依赖网络、Docker 或 API key；具体数量以 `scripts/check.py` 输出为准。
- 先例：基线项目没有测试；按 pytest 常规组织，避免引入额外框架。

## Out of Scope

- 安装 Tesseract / 完整中文 OCR；真正的扫描页保持显式缺口。第 29 页有可读文字层，是分节页而非扫描页，不需要 OCR。
- 多 PDF 知识库、增量索引、索引持久化与版本迁移。
- Reranker / cross-encoder。
- LangChain、LlamaIndex、向量数据库服务、LangGraph。
- 完整 NLI 模型、中文 NER、人工 fact-check 审批 UI。
- Groq / HuggingFace / Together 等多余 provider、聊天问答 UI、聊天历史、PDF 导出。
- 公网部署、Demo 录屏（本轮选择只交可运行 Demo）。
- 20 条 AC 全量矩阵、Streamlit AppTest E2E、鉴权/多租户/生产监控；但题目“二、AI 工程”的逐条映射是交付物，不受此限。
- 数字/日期/百分比/否定词之外的确定性实体校验。

## Further Notes

- **已确认的决策**：复用 PDF 解析但重写 chunker（Q7-A）、能力组合 A（Q8-A）、本地准备 Docker/本地 bge-m3 与 DeepSeek key（Q9-A）、归档旧规划文档（Q10-A）、提交真实示例产物（Q11-A）。
- **2026-10-25 复盘决策**：题目“输出结构完整的文章，包括标题、导语、小标题和结尾”按四种内容类型统一执行；品牌介绍/产品介绍旧示例（无导语）由 `PROMPT_VERSION=2026-10-25.3` 的真实运行替换。需求逐条映射与交付护栏纳入本 Spec，不再只靠 README 表格。
- **环境现状（2026-10-25 更新）**：默认使用本地 `bge-m3`（项目 `rag/data/bge-m3` 与用户 ModelScope 缓存），已从任意工作目录完成真实索引/检索；Docker Ollama 作为可选路径也已完成真实验证（`ollama/ollama:latest`，容器 `trendee-ollama` 只绑定 `127.0.0.1:11434`，`bge-m3:latest` 1024 维）。`rag/.env` 已配置 DeepSeek，key 不进入版本库；Tesseract 未安装；Python 3.11.15 venv 已装齐依赖。PDF 共 36 页，33 页有文本/43 个 chunk，第 1、8、29 页无 chunk，第 29 页为含可读文字的分节页。逐项真实结果见 `docs/verification.md`。
- **时间与降级**：目标今晚提交。若时间不足，按以下顺序降级：先去掉 entailment 校验（文章固定 `partial` + manual review），再减少单测，但必须保留引用编号、页码来源、无证据拒答和示例产物。
- **Issue tracker**：本仓库使用 Local Markdown tracker，Spec 与 tickets 位于 `.scratch/rag-brand-writer/`。
- **Seam 确认**：已确认采用两个 pipeline seam（ingestion + writing），外加一次手动真实 E2E；不单独增加 citation validator 纯函数 seam，不做 Streamlit AppTest。
