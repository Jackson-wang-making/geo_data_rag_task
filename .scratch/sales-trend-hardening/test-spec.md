# Test Specification: sales-trend 高并发与范围口径加固

- Status: ready-for-agent
- Baseline: `sales-trend/`，34 passed
- Related Spec: `.scratch/sales-trend-hardening/spec.md`

## 1. Test Goal

证明 H1/H2/H3 落地后：`day` 粒度不再被 366 天卡死、coverage 不再每请求扫 raw、连接复用、文档与实现一致，且**原有 34 条测试不回归**。

## 2. Test Environment

| Item | Value |
|---|---|
| Runtime | `sales-trend/`，Python 3.12，`docker compose up` 已起 PostgreSQL |
| DB | `postgres:16-alpine`，`sales_trend` |
| Test runner | pytest；集成测试需 `DATABASE_URL` |
| 命令 | `docker compose run --rm api pytest -q`（全量，含集成） |

## 3. Test Cases

### FR-SCALE-01 任意日期范围

| ID | Input | Expected |
|---|---|---|
| UT-RANGE-01 | `granularity=day`，`start=2024-01-01&end=2025-01-01`，单平台 | `200`，`resolved_granularity=day`，series 长度 = 天数 |
| UT-RANGE-02 | `granularity=day`，跨多平台 | series 长度 = 天数 × 平台数，总销量 = 各平台求和 |
| UT-RANGE-03 | `granularity=day`，`period_count × platform_count > MAX_SERIES_POINTS` | `422 RANGE_TOO_LARGE`，`details.max_points/requested_points` 存在 |
| UT-RANGE-04 | `granularity=auto`，跨 2 年 | 仍粗化为 week/month（不回归） |
| UT-RANGE-05 | `fill_missing=false`，长范围 | 仅返回有数据的点，不做大范围补零 |
| UT-RANGE-06 | 短范围 day（原 42 例） | `total_sales=42`，行为不变 |

### FR-SCALE-02 coverage 预计算

| ID | Input | Expected |
|---|---|---|
| UT-COV-01 | ETL 完成后查 `app.coverage_meta` | 存在 `scope='raw_source'`，`min_date=2024-01-01`，`max_date=2024-03-13` |
| UT-COV-02 | API `meta.coverage` | `min_date/max_date` 与 UT-COV-01 一致 |
| UT-COV-03 | 空 `coverage_meta` | `CoverageRecord(None, None)`，不报错 |
| UT-COV-04 | `inspect.getsource(repository)` | `get_coverage` 引用 `app.coverage_meta`，不引用 `raw.sales_data` |

### FR-SCALE-03 连接池

| ID | Input | Expected |
|---|---|---|
| UT-POOL-01 | `requirements.txt` | 含 `psycopg_pool` |
| UT-POOL-02 | 无 `DATABASE_URL` 导入 app | 不建 pool、不报错（惰性创建） |
| UT-POOL-03 | `_fetchall` 源码 | 从 pool 取连接，仍含 `SET LOCAL statement_timeout` |
| IT-POOL-01 | 连续 N 次 API 请求 | 全部 `200`，无连接耗尽；幂等 ETL 二次执行 `raw_rows_inserted=0` |

### FR-DOC-01 文档一致性

| ID | 检查 | Expected |
|---|---|---|
| CHK-DOC-01 | `architecture.md` 错误码表 | 不含 `429 RATE_LIMITED` 作为已实现项 |
| CHK-DOC-02 | `README.md` 错误码表 | 与实现一致（无 429 或标注生产扩展） |
| CHK-DOC-03 | `architecture.md` §15 | 明确列出未实现的生产扩展（Redis/读副本/PgBouncer/限流/连接池/coverage 预计算/366 上限） |

## 4. Regression

- 原 34 条测试除 `tests/test_api.py` 中「day 跨 367 天 → 422」一条外全部保持原样通过；该条按 FR-SCALE-01 新语义更新为 `200`。

## 5. Release Gate

- [ ] 新增 UT-RANGE/UT-COV/UT-POOL/CHK-DOC 全部 PASS。
- [ ] 原测试回归通过（允许按 spec 明确列出的更新）。
- [ ] `EXPLAIN` 证据显示 `get_coverage` 不再扫 `raw.sales_data`。
- [ ] 文档与实现一致。
