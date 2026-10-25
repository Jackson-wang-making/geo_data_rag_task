# Playwright E2E drills

这些脚本驱动真实 Chrome 打开 Streamlit，用于验证真实索引、生成、下载和
fail-closed 分支。它们不进入默认 pytest；需要 Node.js 18+、Chrome 和真实的
本地 embedding / `.env` 配置。

## 安装

```bash
cd rag/scripts/e2e
npm ci
```

脚本默认使用项目虚拟环境的 Python（`rag/.venv`）和本地 bge-m3。输出写入
`rag/scripts/e2e/out/`（已忽略），不会写入 `rag/artifacts/`。需要换目录时设置
`E2E_OUT`。

## 运行

`p1`、`p2` 使用手动启动的 8501 应用；`p3`、`p4`、`p4b`、`p5` 会各自启动/停止独立端口。先启动 8501：

```bash
cd rag
.venv/Scripts/python.exe -m streamlit run app.py
```

另开一个终端：

```bash
cd rag/scripts/e2e
node p2_generate_downloads.js      # 真实生成 + 点击两个下载按钮
node p3_missing_key.js             # 清空 LLM_API_KEY，断言 LLM_UNAVAILABLE
node p4b_local_embed_failure.js    # 本地模型指向空目录，断言 EMBED_UNAVAILABLE
node p4_embed_outage.js            # Ollama 指向关闭端口，断言 EMBED_UNAVAILABLE
node p5_faq_ui.js                  # FAQ 生成与人工复核区域
```

`p1_upload_reindex.js` 需要另一份小 PDF：

```bash
E2E_OTHER_PDF=/path/to/brochure.pdf E2E_QUERY="document topic" node p1_upload_reindex.js
```

默认 fixture 是 `out/raku-6d-brochure.pdf`（未入库）；缺失时脚本打印 `SKIP`。若使用其他 PDF，必须同时提供 `E2E_QUERY`，否则只做上传/重索引断言并明确打印 `RETRIEVAL_SKIPPED`，不会把空检索当成通过。`p4b` 默认创建 `out/empty-bge-m3`；`E2E_EMPTY_MODEL_DIR` 的相对路径按 `rag/` 解析。`p5` 默认使用 `EMBEDDING_PROVIDER=local`；如需 Docker Ollama，设置 `E2E_EMBEDDING_PROVIDER=ollama` 和可选的 `OLLAMA_BASE_URL`。

## 安全

- 不打印 `process.env`、请求头、`.env` 或页面里的完整 prompt。
- 截图/下载/日志只落在 `out/`，该目录不进入版本库。
- 失败时脚本以非零退出码结束；`SKIP` 不是 PASS。

## 证据去向

脚本写出的文件名与 `rag/examples/screenshots/` 中的证据一一对应：

| 脚本 | 截图 |
| --- | --- |
| `p1_upload_reindex.js` | `05-upload-reindex.png`、`06-upload-retrieval.png` |
| `p2_generate_downloads.js` | `07-article-downloads.png`、`08-after-downloads.png` |
| `p3_missing_key.js` | `09-llm-unavailable.png` |
| `p4_embed_outage.js` | `10-embed-unavailable.png` |
| `p5_faq_ui.js` | `11-faq-partial.png` |
| `p4b_local_embed_failure.js` | `12-local-embed-unavailable.png` |

运行后把 `out/` 中的截图复制到 `rag/examples/screenshots/`（保持文件名不变）。
运行结果、run ID 和 SHA 记录在 `rag/docs/verification.md`；需求逐条映射见
`rag/docs/requirements-traceability.md`。
