# 四种内容类型的真实产物

本目录保存 2026-10-25 真实运行产生的 FAQ、品牌介绍、产品介绍 `article.md` 和 `evidence.json`；Blog 的 real 产物在上级 `examples/`。它们都不是 fake LLM / fake embedder 输出。当前默认 embedding 是本地 `bge-m3`（`EMBEDDING_PROVIDER=local`）；表中标为 Docker Ollama 的运行是当时显式设置 `EMBEDDING_PROVIDER=ollama` 的历史证据，不代表当前默认。每次运行的 `evidence.json` 都包含 topic、content_type、embedding provider/model、检索参数、来源页码、LLM 参数、逐条校验结果和 run ID。

| 类型 | run ID | Embedding | 状态 | 关键结果 |
| --- | --- | --- | --- | --- |
| Blog（UI 点击生成并下载） | `20261025-163101-608707` | Docker Ollama `bge-m3` | `complete` | 10 claims，确定性 0 issue，entailment 10/10 supported；两个下载按钮均实际点击，内容与 artifact 归一化后一致。示例正文见 `../article.md` / `../evidence.json` 的 canonical run `20261025-153905-378062`。 |
| FAQ | `20261025-162006-879084` | 本地 `bge-m3` | `partial` | 12 claims，结构完整，确定性检查通过；entailment 11 supported，`c001` unsupported，保留人工复核项，未伪装成 complete。 |
| 品牌介绍 | `20261025-191039-455324` | 本地 `bge-m3` | `complete` | 17 claims，确定性 0 issue，未修复，entailment 17/17 supported，`finish_reason=stop`；新增导语段。 |
| 产品介绍 | `20261025-191140-386813` | 本地 `bge-m3` | `partial` | 16 claims，结构完整（含导语），确定性 0 issue，`finish_reason=stop`；entailment 15/16 supported，`c001` unsupported，保留人工复核项。 |

## 说明

- Blog 的 canonical 示例仍是 `../article.md` / `../evidence.json`（run `20261025-153905-378062`，`complete`，本地 bge-m3）。本目录不重复保存同一篇 Blog。
- 品牌介绍与产品介绍已按 `PROMPT_VERSION=2026-10-25.3` 重跑：四种内容类型现在都要求 H1 与第一个 H2 之间有导语；旧的无导语 Docker Ollama 示例已被取代。
- 表中 Blog UI run 使用显式 Docker Ollama；FAQ、canonical Blog、品牌介绍和产品介绍使用本地 bge-m3。两种 provider 均为 1024 维，检索与校验逻辑一致。
- FAQ 与产品介绍的 `partial` 是 verifier 真正给出的 `unsupported`，不是生成失败；页面会展示人工复核项。
- 产品介绍上一轮曾因两处确定性误伤重新生成；本轮 `c001` 是语义层面的 `unsupported`，系统按 fail-closed 规则保留 `partial`，没有伪装成 `complete`。
- 这些文件不含 API key、完整 prompt 或请求头。运行时 artifact 在 `rag/artifacts/`，已被 `.gitignore` 排除。
