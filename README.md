# 万悉科技 AI 数据工程师笔试工作区

## 目录结构

```text
.
├── inputs/
│   ├── exam/       # 笔试题、题目要求和 PDF
│   ├── brand/      # Trendee 品宣 PDF/Markdown 与图片
│   └── sales/      # 样例销售数据及元数据说明
├── sales-trend/    # 第一题：销售数据查询与 API
├── rag/            # 第二题：品牌内容 RAG 写作系统
└── .omx/           # OMX 运行时状态，不进入交付
```

## 项目整体启动与关闭

两个子项目相互独立，可以只启动其中一个；需要同时运行时，开两个 PowerShell 终端。

前置条件：

- Docker Desktop 已启动（第一题使用；第二题的 Docker Ollama 为可选项）。
- `rag/.venv` 已创建并安装依赖，`rag/.env` 已配置 DeepSeek；首次安装见 [rag/README.md](rag/README.md) 的“快速开始”。
- 第一题首次启动会自动建库、执行 schema 并导入样例销售数据。

### 启动

终端 1：第一题（PostgreSQL + ETL + FastAPI）

```powershell
cd .\sales-trend
docker compose up --build -d
docker compose ps
```

- API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- 启动顺序为 `db healthy → etl 导入样例 → api 启动`；`docker compose ps` 中 `api` 为 `running` 即可访问。
- 若 `5432` 或 `8000` 被占用，先设置 `$env:DB_PORT = "55432"` 或 `$env:API_PORT = "8001"`，再执行 `docker compose up --build -d`。

终端 2：第二题（Streamlit）

```powershell
cd .\rag
.venv\Scripts\python.exe -m streamlit run app.py
```

- 打开 `http://127.0.0.1:8501`。
- 首次启动会解析 PDF、加载本地 `bge-m3` 并建立索引，需要等待页面提示索引完成。
- 若 `8501` 被占用：`.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502`。

默认使用本地 `bge-m3`，不需要 Ollama。只有显式改用 Docker Ollama 时，才在终端 2 启动 Streamlit 前执行：

```powershell
docker start trendee-ollama
$env:EMBEDDING_PROVIDER = "ollama"
.venv\Scripts\python.exe -m streamlit run app.py
```

### 关闭

- 第二题：在运行 Streamlit 的终端按 `Ctrl+C`。关闭浏览器标签页不会停止后台进程。
- 第一题：在任意终端执行：

```powershell
cd .\sales-trend
docker compose down
```

`docker compose down` 会停止并删除容器和网络，但保留 PostgreSQL 数据卷，下次启动不会重复导入。需要连同数据库数据一起清空时使用 `docker compose down -v`（会删除样例数据，下一次启动重新导入）。

- 可选 Ollama：如果启动过 `trendee-ollama`，执行 `docker stop trendee-ollama`。

## 第一题：销售趋势

```powershell
cd .\sales-trend
Get-Content .\README.md
```

项目已包含样例数据副本和独立测试。

## 第二题：RAG 品牌写作

```powershell
cd .\rag
Get-Content .\README.md
Get-Content .\SPEC.md
.venv\Scripts\python.exe -m streamlit run .\app.py
```

- 输入 PDF：`inputs/brand/Trendee品宣-公开版.pdf`（应用自动加载）
- 代码结构：`rag/app.py` 是 Streamlit 入口；核心逻辑在 `rag/trendee_rag/`（`knowledge.py`、`embeddings.py`、`llm.py`、`writer.py`、`validation.py`、`artifacts.py`）。模块职责见 [rag/README.md 的项目结构](rag/README.md#项目结构)。
- 验收基准：`inputs/exam/万悉科技AI数据工程师笔试题.md`（任务二）；逐条映射与证据：`rag/docs/requirements-traceability.md`
- 实现依据：`rag/SPEC.md`；任务票：`.scratch/rag-brand-writer/issues/`
- 交付前自检：`cd rag; .venv\Scripts\python.exe scripts\check.py`（compile + pytest + secret scan）
- 当前状态：ticket 01–05 的代码、文档、示例产物和截图已完成；检索、四种内容类型生成、确定性引用校验、一次修复、entailment verifier、来源卡片与 `article.md` / `evidence.json` 下载均已接入。手动验收项全部执行，见 `rag/docs/manual-e2e-checklist.md`。
- 自动化测试：`88 passed`（fake embedder / fake LLM，无网络）。
- 真实 E2E：默认本地 bge-m3 与可选 Docker Ollama 两条路径都已跑通，使用 DeepSeek `deepseek-flash` + Streamlit。Blog canonical run `20261025-153905-378062`（本地 bge-m3）为 `complete`（10 条来源、10 条 claim、entailment 10/10）；UI 点击生成 run `20261025-163101-608707`（显式 Docker）同样为 `complete`。FAQ `20261025-162006-879084`、品牌介绍 `20261025-191039-455324`、产品介绍 `20261025-191140-386813` 均来自真实运行；品牌介绍按 prompt `2026-10-25.3` 重跑并含导语，为 `complete`（17/17 supported）；产品介绍含导语，为 `partial`（15/16 supported，`c001` unsupported）。系统按 fail-closed 规则保留问题，不伪装成 `complete`。真实产物在 `rag/examples/`，截图在 `rag/examples/screenshots/`。
- 已实际执行的边界：默认本地 bge-m3 索引/检索、可选 Docker Ollama 索引与生成、上传 Raku 宣传 PDF、FAQ/品牌介绍/产品介绍真实生成、缺失 key 演练、默认本地模型加载失败、可选 Ollama 中断、verifier 失败矩阵、prompt injection、实际点击两个下载按钮。逐项结果、run ID、截图和 SHA 见 `rag/docs/verification.md`。
- 默认 embedding：本地 `sentence-transformers` `bge-m3`（`EMBEDDING_PROVIDER=local`，`rag/data/bge-m3`，1024 维），不需要 Docker。可选 Docker embedding：`RUN`，镜像 `ollama/ollama:latest`（`sha256:dea72d…`），容器 `trendee-ollama` 只绑定 `127.0.0.1:11434`，模型 `bge-m3:latest`（1024 维）；只有显式 `EMBEDDING_PROVIDER=ollama` 时启用。
- 上游：ChatPDF，MIT License，commit `92a853a`；来源、修改说明与 MIT 归属见 [rag/THIRD_PARTY_NOTICES.md](rag/THIRD_PARTY_NOTICES.md)，许可条款见 [rag/LICENSE](rag/LICENSE)

## 清理说明

旧 `rag/` 基础设施方案、旧 RAG PRD/Test/Review、UltraGoal/UltraQA 记录和误生成空文件已删除。第一题资料保留并归档到 `inputs/` 与 `sales-trend/`。
