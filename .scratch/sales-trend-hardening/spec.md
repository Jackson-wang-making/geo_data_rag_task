# Implementation Spec: sales-trend 高并发与范围口径加固

- Status: ready-for-agent
- Baseline: `sales-trend/`，Docker `docker compose up` 后 34 passed（2026-10-25 实测）
- Related: `sales-trend/docs/architecture.md`、`sales-trend/README.md`
- Tickets: `issues/01..04`

## 1. Purpose

把核对报告中的硬缺口 H1/H2/H3 与文档一致性问题 S2 落地为可验证行为。不改变 maxi dress 识别口径、三层模型、API 路径，不新增存储引擎或外部服务。

## 2. Scope

| ID | 内容 | 类型 |
|---|---|---|
| FR-SCALE-01 | 任意日期范围：`day` 粒度取消 366 天硬上限，改为返回点数上限 | 行为变更 |
| FR-SCALE-02 | coverage 预计算：不再每请求扫描 `raw.sales_data` | 行为变更 |
| FR-SCALE-03 | 连接池：`psycopg_pool`，单进程共享连接 | 行为变更 |
| FR-DOC-01 | 文档一致性：`429 RATE_LIMITED`/限流 与实现对齐 | 文档 |

## 3. Functional Requirements

### FR-SCALE-01 任意日期范围（H1）

- `GET /v1/sales/trends` 的 `granularity=day` 接受任意合法 `start_date <= end_date`，不再有固定 366 日历天上限。
- 唯一上限是返回 `series` 点数 `period_count × platform_count`，默认 `MAX_SERIES_POINTS = 100_000`（env 可配）。
- 超过上限返回 `422 RANGE_TOO_LARGE`，`details` 含 `{max_points, requested_points}`。
- `granularity=auto` 保持现有 day/week/month 粗化阈值（`DAY_MAX_DAYS=366`、`AUTO_WEEK_MAX_DAYS=1464`）不变，不随本项改动。
- `_resolve_granularity` 新增 `platform_count` 入参，仅显式 `day` 分支使用 `MAX_SERIES_POINTS` 判定。

受影响的既有测试（需按新语义更新，不得绕过）：

- `tests/test_api.py` 中 `granularity=day` 跨 367 天期望 `422 RANGE_TOO_LARGE` 的参数化用例：改为期望 `200`（367×1 平台 < 100k），另补一个真正超 `MAX_SERIES_POINTS` 的用例仍断言 422。
- `test_auto_switches_away_from_day_for_long_ranges` 不受影响，保持 `auto -> week`。

### FR-SCALE-02 coverage 预计算（H2）

- 新增单行表 `app.coverage_meta(scope text PRIMARY KEY, min_date date, max_date date, updated_at timestamptz NOT NULL)`。
- ETL 在 raw 导入后、应用层刷新前，按 `raw.sales_data` 计算 `("timestamp" AT TIME ZONE 'Asia/Shanghai')::date` 的 MIN/MAX，UPSERT `scope='raw_source'`。
- `PostgresSalesTrendRepository.get_coverage()` 只读 `app.coverage_meta`，不再查询 `raw.sales_data`。
- 无行时返回 `CoverageRecord(min_date=None, max_date=None)`，不报错。
- 新 SQL 文件 `sql/005_coverage.sql`（幂等），与既有 `apply_schema` 顺序兼容。

### FR-SCALE-03 连接池（H3）

- `requirements.txt` 新增 `psycopg_pool`。
- 引入惰性创建的 `psycopg_pool.ConnectionPool`，`min_size=1, max_size=10, timeout=5`，由 `DATABASE_URL` 构建，进程内共享。
- `PostgresSalesTrendRepository` 的连接从 pool 获取，取代逐次 `psycopg.connect`。
- 每连接仍执行 `SET LOCAL statement_timeout = '5000ms'`。
- 测试注入 fake repository 保持隔离；pool 仅在真实 Postgres repository 中创建，应用可无库导入。

### FR-DOC-01 文档一致性（S2）

- `docs/architecture.md` 不再把 `429 RATE_LIMITED` 列为已实现错误码；限流标注为生产扩展（本项已随文档修正落地，ticket 04 负责校验并复检 README 一致性）。

## 4. Data Contracts

### 4.1 `app.coverage_meta`

```sql
CREATE TABLE IF NOT EXISTS app.coverage_meta (
    scope      text PRIMARY KEY,
    min_date   date,
    max_date   date,
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

`scope` 固定为 `raw_source`；`min_date/max_date` 语义与现有 `meta.coverage` 返回一致（raw 源覆盖，非 maxi-dress 结果覆盖）。

## 5. Component Interfaces

### 5.1 `SalesTrendRepository`（Protocol）

签名不变；`get_coverage()` 语义不变（返回 `CoverageRecord`），仅实现来源从 raw 表改为 `app.coverage_meta`。

### 5.2 `PostgresSalesTrendRepository`

- 新增 `_pool()`：惰性解析共享 `ConnectionPool`。
- `_fetchall()` 改为 `with self._pool().connection() as conn:`。
- 常量 `MAX_SERIES_POINTS` 读 env `MAX_SERIES_POINTS`，默认 `100_000`。

## 6. Configuration Contract

| Variable | Default | Behavior |
|---|---:|---|
| `MAX_SERIES_POINTS` | `100000` | `series` 返回点数上限（day/week/month 通用保护） |

## 7. Error Codes

- `422 RANGE_TOO_LARGE`：语义扩展为「返回点数超限」；`details.max_points / requested_points`。
- 其余错误码不变。`429 RATE_LIMITED` 不新增（留待生产扩展）。

## 8. Non-functional

- 不改变 34 条既有测试的通过性（除 FR-SCALE-01 明确列出的两处）。
- 不引入 Redis / ClickHouse / 新服务；依赖新增仅 `psycopg_pool`。
- 保持「无库可导入 FastAPI app」的既有约定（pool 惰性创建）。

## 9. Definition of Done

- FR-SCALE-01/02/03 均有代码路径 + 单测/集成测试通过。
- `docker compose up` 后全量测试（原 34 + 新增）通过。
- `EXPLAIN` 证明 `get_coverage` 不再扫 `raw.sales_data`。
- `architecture.md` / `README.md` 与实现一致（含 366 上限与 coverage 来源的最终口径）。

## 10. Ticket map

| Ticket | FR | 优先级 |
|---|---|---|
| `01-unbounded-day-range` | FR-SCALE-01 | P0 |
| `02-precompute-coverage` | FR-SCALE-02 | P0 |
| `03-connection-pool` | FR-SCALE-03 | P0 |
| `04-doc-rate-limit-consistency` | FR-DOC-01 | P1 |
