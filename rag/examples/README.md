# 真实运行示例

本目录的 `article.md`、`evidence.json` 和 `screenshots/` 来自 2026-10-25 的 Streamlit 真实运行，不是 fake embedder / fake LLM 测试输出。当前默认 embedding 是本地 sentence-transformers `bge-m3`（`EMBEDDING_PROVIDER=local`）；部分历史截图显式使用了 Docker Ollama（05、06、07/08、11），下方逐张注明。

## 本次运行

- Run ID：`20261025-153905-378062`
- 主题：`为什么中国出海品牌需要 GEO 优化`
- 内容类型：Blog
- Embedding：本地 `bge-m3`（`EMBEDDING_PROVIDER=local`，CPU，1024 维，L2 归一化）
- 写作与校验：DeepSeek `deepseek-flash`，temperature 0.2，`max_output_tokens=8000`
- Prompt 版本：`2026-10-25.2`
- 索引：36 页 PDF，33 页有 chunk，43 个 chunk；第 1/8/29 页是封面或分节页，没有可索引正文
- 检索：10 条证据，覆盖 PDF 第 4/12/14/16/19/25/31/32/33/34 页；dense 分数 0.501–0.624；未发生上下文截断
- 校验：确定性引用检查通过（10 条 claim，0 个 issue）；entailment 10/10 为 `supported`
- 状态：`complete`

## 为什么是 `complete`

本次生成没有触发自动修复，`finish_reason=stop`，结构完整，确定性引用检查 0 issue，且 verifier 对全部 10 条事实性 claim 都返回 `supported`。这是状态机允许 `complete` 的全部条件，`evidence.json` 中 `validation.deterministic.passed=true`、`validation.repair_attempted=false`、`validation.entailment.passed=true`、`manual_review_items=[]` 均可核对。

页面上方“数据覆盖”显示 `coverage_status=partial`，与文章状态无关：它只表示第 1/8/29 页没有可索引正文。文章状态 `complete` 表示本次使用的 10 条证据足以支撑生成内容并通过校验。

同一提示词下也出现过不理想的真实结果：例如 `20261025-153754-654372` 的 `c001` 为 `uncertain`，`20261025-153704-413835` 在自动修复后仍有一处确定性引用问题，二者都保持 `partial`。本示例选择的是校验结果最好的一次，不表示系统每次都能达到 `complete`；出现 `partial` 时仍会展示问题并列出人工复核项。

## 文件

- `article.md`：正文，末尾附来源清单（编号、文档名、PDF 页、section、excerpt）。
- `evidence.json`：本次运行的检索参数、来源、覆盖率、LLM 参数、prompt 版本、逐条校验结果、状态和 run 元数据。
- `screenshots/`：真实 UI 截图；`01-coverage.png` 显示自动加载与覆盖率指标（36 页 / 33 页有 chunk / 43 个 chunk / OCR 不可用 0），`02-article.png` 显示 `complete` 与绿色校验通过提示，`03-sources.png` 显示 10 张来源卡片、citation support 分数和下载按钮，这三张来自上面的 complete run。`04-insufficient.png` 来自单独的 fail-closed run `20261025-153911-888736`（主题为 Rust 内核，`status: insufficient`），截图底部可见该产物路径。
- `05-upload-reindex.png`：通过真实上传控件载入 Raku 宣传 PDF 后重新索引，指标从 36/33/43 变为 9/8/16，sidebar 显示当时显式使用的 Docker Ollama 与 `bge-m3`。
- `06-upload-retrieval.png`：同一份 Raku PDF 的检索预览（Docker Ollama），10 条证据覆盖 7 页，来源全部是 `raku-6d-brochure.pdf`。
- `07-article-downloads.png`：真实生成后的 `complete` 结果与正文（Docker Ollama）；`08-after-downloads.png` 显示来源卡片和两个下载按钮，两个按钮均被实际点击，下载内容与 artifact 校验一致（SHA 见 [../docs/verification.md](../docs/verification.md) §7）。
- `09-llm-unavailable.png`：移除本地 key 后的 `LLM_UNAVAILABLE`，仍保留检索来源，但不生成文章、不写 artifact（默认本地 bge-m3）；`12-local-embed-unavailable.png`：本地 bge-m3 空目录/不可加载时的 `EMBED_UNAVAILABLE`（演练使用临时空目录）；`10-embed-unavailable.png`：可选 Ollama 服务指向关闭端口后的 `EMBED_UNAVAILABLE`。后两者不建立索引、不显示指标或生成按钮。
- `11-faq-partial.png`：UI 选择 FAQ 后生成的真实 `partial` 结果（Docker Ollama，run `20261025-164501-161355`），页面显示“首次生成未通过引用校验，已自动修复一次”；Playwright 同时断言“需要人工复核”展开区域存在且包含问题说明。
- `content-types/`：FAQ、品牌介绍、产品介绍三种内容类型的真实产物与结果表（`README.md`），不是只改了 UI 选项的样例。品牌介绍/产品介绍已按 `PROMPT_VERSION=2026-10-25.3` 重跑并包含导语；FAQ 保留 `2026-10-25.2` 的历史真实 run。

## 核对提示

- 文章中的 `27%` 可在 PDF 第 33 页核对；`20%`、`30 天`、`300+` 在第 32 页；`65%+` 与 Top 1 在第 34 页；Top 1 也在第 31 页。页码与 `article.md` 来源清单一致。
- 文章对 PDF 中“行业名高 300+ 名”的表述保持原样引用；原文本身较生硬，系统没有替它补写或改写指标。
- `evidence.json` 和 `article.md` 不包含 API key、完整 prompt 或请求头。
- 第 1/8/29 页没有可索引文本，不会出现在检索结果中；第 29 页有可读文字层，不需要 OCR。第 18 页的大字号整句主张已通过 chunk 回退进入索引，示例文章没有补写这些页面以外的内容。
