# Trendee Sales Trend API

万悉科技 AI 数据工程师笔试题第一题：基于 PostgreSQL 的 maxi dress 销售趋势查询与 API。

## 1. 项目概览

```text
XLSX
  ↓
raw.sales_data          原始 7 个字段
  ↓
std.sales_clean         去重、时区、归一化标题、explicit 标记
  ↓
app.maxi_dress_daily    日期 + 平台 + product_id + 归一化 title + 销量
  ↓
GET /v1/sales/trends
```

核心特性：

- PostgreSQL 16；
- 原始层、标准层、应用层三层模型；
- explicit-only maxi dress 识别；
- 应用层保留 `product_id` 和归一化 `title`；
- 标准层唯一约束和幂等加载；
- 应用层按受影响日期事务刷新；
- 月度分区；
- coverage 预计算（`app.coverage_meta`），热点查询不扫原始层；
- `psycopg_pool` 连接池复用连接；
- 日粒度按返回点数保护（`MAX_SERIES_POINTS`），不再固定 366 天上限；
- FastAPI + Swagger；
- Docker Compose 一键启动；
- 单元测试 + PostgreSQL 集成测试。

## 2. 目录结构

```text
sales-trend/
├── app/
│   ├── api/routes.py              # GET /v1/sales/trends
│   ├── services/sales_trends.py   # 参数校验、补零、聚合
│   ├── repository.py              # PostgreSQL 查询
│   ├── normalization.py           # API 侧归一化规则
│   ├── models.py                  # Pydantic 响应模型
│   └── main.py                    # FastAPI app
├── etl/
│   ├── loader.py                  # XLSX loader + acceptance gate
│   └── quality.py                 # 数据质量与 explicit 规则
├── sql/
│   ├── 001_schema.sql
│   ├── 002_functions.sql
│   ├── 003_partitions.sql
│   ├── 004_standardize.sql
│   └── 005_coverage.sql
├── tests/
│   ├── test_api.py
│   ├── test_contract.py
│   ├── test_etl_unit.py
│   └── test_integration.py
├── data/sample_sales.xlsx
├── docs/architecture.md
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## 3. 快速启动与关闭

### 3.1 启动

首次启动（构建镜像）：

```powershell
cd sales-trend
docker compose up --build -d
```

之后再次启动可省略 `--build`：

```powershell
docker compose up -d
```

如果本机 5432 端口已被占用，换一个宿主机端口：

```powershell
$env:DB_PORT = "55432"
docker compose up --build -d
```

启动顺序：`db healthy → etl 导入样例 → api 启动`。

### 3.2 查看状态与日志

```powershell
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 etl
```

### 3.3 重启

```powershell
docker compose restart
```

### 3.4 关闭

保留数据库数据卷（下次启动数据仍在）：

```powershell
docker compose down
```

同时删除数据卷、完全重建：

```powershell
docker compose down -v
```

启动后访问：

- API：`http://localhost:8000`
- Swagger：`http://localhost:8000/docs`
- PostgreSQL：宿主机端口 `${DB_PORT:-5432}`

## 4. ETL

### 4.1 自动导入

`docker compose up` 会自动运行 `etl` 服务，导入 `data/sample_sales.xlsx`。

### 4.2 手动重跑

```powershell
docker compose run --rm etl
```

ETL 会执行：

1. 读取 Excel；
2. 按 7 个原始字段计算重复数据；
3. 校验空值、销量、平台等质量规则；
4. 写入原始层；
5. 在标准层执行归一化和 explicit 分类；
6. 按日期范围刷新应用层；
7. 对账 Python 与数据库的质量指标。

样例验收结果：

```text
raw_count=300
duplicate_count=12
accepted_count=288
explicit_count=119
explicit_sales=1117
explicit_product_count=12
platform_sales:
  app=368
  marketplace=372
  website=377
```

重复执行 ETL 时：

- `raw_rows_inserted=0`
- 标准层不重复增加；
- 应用层 `sales_count` 仍为 1117。

### 4.3 本地运行 ETL

需要设置数据库连接：

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:55432/sales_trend"
python -m etl.loader --workbook data/sample_sales.xlsx --verify-sample
```

## 5. API

### 5.1 路径

```http
GET /v1/sales/trends
```

### 5.2 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `start_date` | 是 | 开始日期，包含边界 |
| `end_date` | 是 | 结束日期，包含边界 |
| `category` | 否 | 默认 `maxi dress`，归一化后必须等于该值 |
| `platform` | 否 | 可重复：`website`、`app`、`marketplace`；不传返回全部 |
| `granularity` | 否 | `day`、`week`、`month`、`auto` |
| `timezone` | 否 | v1 仅支持 `Asia/Shanghai` |
| `fill_missing` | 否 | 日期 × 平台无数据时是否补 0，默认 `true` |
| `include_titles` | 否 | 是否返回分页的商品/标题明细，默认 `false` |
| `page` | 否 | 标题明细页码 |
| `page_size` | 否 | 标题明细分页大小，最大 500 |

默认返回日期 × 平台聚合，不会返回无界的标题明细。

`granularity=day` 的返回点数受 `MAX_SERIES_POINTS`（默认 `100000`，可通过环境变量覆盖）保护，超限返回 `422 RANGE_TOO_LARGE`；`auto` 会在 `day`/`week`/`month` 间按跨度粗化，用于长范围图表。

### 5.3 示例请求

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/v1/sales/trends?start_date=2024-01-01&end_date=2024-01-03&platform=app&platform=website"
```

### 5.4 示例响应

```json
{
  "query": {
    "category": "maxi dress",
    "start_date": "2024-01-01",
    "end_date": "2024-01-03",
    "platforms": ["app", "website"],
    "granularity": "day",
    "resolved_granularity": "day",
    "timezone": "Asia/Shanghai",
    "fill_missing": true,
    "include_titles": false,
    "page": 1,
    "page_size": 100
  },
  "data": {
    "series": [
      {"date": "2024-01-01", "platform": "app", "sales_count": 10},
      {"date": "2024-01-01", "platform": "website", "sales_count": 19},
      {"date": "2024-01-02", "platform": "app", "sales_count": 13},
      {"date": "2024-01-02", "platform": "website", "sales_count": 0},
      {"date": "2024-01-03", "platform": "app", "sales_count": 0},
      {"date": "2024-01-03", "platform": "website", "sales_count": 0}
    ],
    "totals": [
      {"platform": "app", "sales_count": 23},
      {"platform": "website", "sales_count": 19}
    ],
    "total_sales": 42
  },
  "meta": {
    "rule_version": "maxi_dress_v1",
    "coverage": {
      "min_date": "2024-01-01",
      "max_date": "2024-03-13",
      "is_complete_quarter": false,
      "coverage_type": "raw_source"
    }
  }
}
```

### 5.5 标题明细

```text
GET /v1/sales/trends?...&include_titles=true&page=1&page_size=100
```

返回：

- `product_id`
- 归一化 `title`
- 日期/平台/销量

标题明细使用分页，避免一次返回过多数据。

### 5.6 错误码

| HTTP | code | 说明 |
|---|---|---|
| 400 | `INVALID_QUERY` | 参数格式错误 |
| 400 | `INVALID_DATE_FORMAT` | 日期格式错误 |
| 400 | `INVALID_DATE_RANGE` | 开始日期晚于结束日期 |
| 400 | `UNSUPPORTED_CATEGORY` | 归一化后不是 `maxi dress` |
| 400 | `INVALID_PLATFORM` | 平台不在白名单 |
| 400 | `INVALID_TIMEZONE` | 时区不是 `Asia/Shanghai` |
| 422 | `RANGE_TOO_LARGE` | 日粒度返回点数或分页大小超限 |
| 503 | `DATABASE_UNAVAILABLE` | 数据库不可用 |
| 500 | `INTERNAL_ERROR` | 未预期错误 |

## 6. 数据结构

### 6.1 原始层

`raw.sales_data` 严格保留 Excel 的 7 个字段：

```text
product_id, title, sales_count, timestamp, user_id, category, source
```

### 6.2 标准层

`std.sales_clean` 保留原始字段，并增加：

- `title_norm`：token 排序后的归一化标题；
- `business_date`：`Asia/Shanghai` 业务日期；
- `is_maxi_dress`：explicit-only 命中标记。

重复加载由唯一约束保证幂等：

```text
(product_id, title, sales_count, timestamp, user_id, category, source)
```

### 6.3 应用层

`app.maxi_dress_daily`：

```text
stat_date, source, product_id, title, sales_count
```

其中 `title` 是归一化标题。应用层按 `stat_date` 月分区，并通过：

```sql
SELECT app.refresh_maxi_dress_daily(start_date, end_date);
```

执行事务式受影响日期刷新。

## 7. maxi dress 规则

只保留 explicit：

```text
category = dress
AND title_norm 含 maxi token
AND title_norm 含 dress token
```

不会纳入：

- `Elegant Long Dress`：没有 `maxi`；
- `Maxi Skirt`：category 不是 dress；
- `Summer Mini Dress`：没有 `maxi`；
- `T-shirt Dress`：category 不是 dress。

`MAXI DRESS WHITE`、`Women's Maxi-Dress Floral`、`Maxi Denim Dress` 等会命中。

## 8. 时间与重复数据

- 原始 timestamp 为 naive datetime，按 `Asia/Shanghai` 解释；
- 标准层存 `timestamptz`；
- `business_date` 由业务时区生成；
- 样例包含 `2024-01-31 23:55`、`2024-02-01 00:05` 等边界值；
- 重复样例按 7 字段完全重复判断；
- 生产环境建议上游提供稳定 `source_event_id`，避免把两条合法但字段完全相同的事件误合并。

## 9. 测试

### 9.1 本地单元测试

```powershell
python -m pytest -q -m "not integration"
```

### 9.2 PostgreSQL 集成测试

先启动数据库和加载样例：

```powershell
$env:DB_PORT = "55432"
docker compose up -d db
docker compose run --rm etl
docker compose run --rm api pytest -q tests/test_integration.py
```

集成测试验证：

- 300 raw → 288 clean；
- explicit 119 行、1117 销量、12 商品；
- 重复加载不重复计数；
- API 日期/平台结果；
- SQL 与 Python 归一化规则一致；
- `include_titles` 返回归一化标题。

### 9.3 性能检查

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT stat_date, source, sum(sales_count)
FROM app.maxi_dress_daily
WHERE stat_date BETWEEN DATE '2024-01-01' AND DATE '2024-03-13'
  AND source = ANY(ARRAY['app', 'website'])
GROUP BY stat_date, source;
```

检查项：

- 只扫描相关月份分区；
- 不扫描原始层；
- 使用应用层主键/索引；
- 响应行数约为日期数 × 平台数。

## 10. 设计取舍

- **PostgreSQL**：样例规模下事务、约束、UPSERT、分区和运维成本最平衡；
- **预聚合**：应用层降低高并发查询成本；
- **标题归一化**：保留 `product_id`，避免不同商品同标题被错误合并；
- **无异常表**：原始层保留全部数据，ETL 质量日志记录拒绝原因和数量；
- **Redis/只读副本/PgBouncer**：生产高并发时再加，示例项目先保证可运行性和可验证性；
- **ClickHouse**：仅在未来原始事件达到每天数千万到数亿级时考虑，不为样例提前拆库。

## 11. 已知边界

- 当前样例只有 2024-01-01 到 2024-03-13，不是完整 Q1；
- `sales_count` 按增量销量求和，若上游提供累计快照需先做 de-snapshot；
- v1 只支持 `Asia/Shanghai`；
- 标题归一化目前针对英文 token，中文/多语言标题需要扩展规则和测试；
- 本项目的 target 是笔试可运行 Demo，不包含生产级 Redis 集群、Kubernetes 或在线扩容脚本。
