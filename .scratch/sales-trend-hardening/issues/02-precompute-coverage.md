# 02: Precompute coverage（不再每请求扫 raw）

**What to build:** 新增 `app.coverage_meta` 单行表，ETL 写入 raw 源覆盖的 min/max 日期；`get_coverage()` 改为读该表，不再每请求扫描 `raw.sales_data`。

**Blocked by:** None

**Status:** done

- [x] 新增 `sql/005_coverage.sql`：`app.coverage_meta(scope text PK, min_date date, max_date date, updated_at timestamptz)` + 幂等 UPSERT 函数。
- [x] `etl/loader.py` 在 raw 导入后、应用层刷新前调用 coverage 刷新（scope=`raw_source`，语义与现有 `meta.coverage` 一致）。
- [x] `PostgresSalesTrendRepository.get_coverage()` 改为查 `app.coverage_meta`；无行返回 `(None, None)`。
- [x] 新增 `UT-COV-01..04` 测试全部 PASS。
- [x] `EXPLAIN` 证据：`get_coverage` 不再出现 `Seq Scan on sales_data`。
