# 万悉科技销售趋势查询：数据工程架构方案

> 题目：一、数据工程：销售数据查询与 API 设计  
> 存储：PostgreSQL 16  
> 核心口径：只保留 explicit 的 maxi dress 识别规则，不使用 `long dress` 同义词口径。  
> 架构：`原始层 → 标准层 → 应用层`。

## 1. 方案结论

采用 PostgreSQL + 三层数据模型 + 每日预聚合 + FastAPI：

```text
样例销售数据.xlsx / 后续数据源
        ↓
raw.sales_data              原始 7 个字段
        ↓
std.sales_clean             去重、时区、标题归一化、explicit 标记
        ↓
app.maxi_dress_daily        日期 + 平台 + product_id + 归一化标题 + 销量
        ↓
GET /v1/sales/trends
```

设计原则：

- 原始层严格保留 Excel 的 7 个业务字段；
- 标准层只增加 3 个必要派生字段；
- 应用层保留 `product_id` 和归一化 `title`，避免把不同商品简单合并；
- 分类在 ETL 阶段完成，API 不重新扫描原始明细；
- 通过唯一约束和受影响日期刷新保证重复运行不重复计数。

## 2. 题目验收映射

| 题目要求 | 方案 |
|---|---|
| maxi dress 日销量趋势 | `app.maxi_dress_daily` + `GET /v1/sales/trends` |
| start_date/end_date | `business_date` 范围过滤，包含首尾日期 |
| 一个或多个平台 | `platform` 可重复；映射到原始 `source` |
| maxi dress 识别/归一化 | category gate + 标题 token 规则，只识别 explicit |
| schema/mapping/index | 原始层、标准层、应用层三层表结构 |
| 核心 SQL | 标准层生成 SQL、应用层聚合 SQL、趋势查询 SQL |
| REST API 和错误处理 | 路径、参数、响应、错误码、范围边界 |
| 大数据量/高并发 | 预聚合、分区、索引、Redis、只读副本、PgBouncer |
| 重复数据 | 7 字段精确去重 + 标准层唯一约束 + 幂等加载 |
| timestamp/时区 | 原始 naive timestamp 按 `Asia/Shanghai` 解释，存 `timestamptz` |
| 异常记录 | 原始层保留全部数据；ETL 过滤并记录批次质量指标，不新增异常表 |
| 工程落地 | Docker Compose、FastAPI、ETL、SQL、测试、README |

## 3. 样例数据画像

对 `样例销售数据.xlsx` 重新计算：

| 指标 | 结果 |
|---|---:|
| 原始记录 | 300 |
| 完全重复记录 | 12 组，多出 12 行 |
| 去重后记录 | 288 |
| explicit 商品数 | 12 |
| explicit 记录数 | 119 |
| explicit 总销量 | 1117 |
| app 销量 | 368 |
| marketplace 销量 | 372 |
| website 销量 | 377 |

样例时间范围是 `2024-01-01 07:00` 至 `2024-03-13 09:45`，不是完整 Q1。

已确认排除：

- `Maxi Skirt`：category 是 skirt；
- `Elegant Long Dress`：没有 maxi token；
- `Summer Mini Dress`：没有 maxi token；
- `T-shirt Dress`：category 是 shirt，且没有 maxi/long 规则。

## 4. 字段映射

### 4.1 Excel 原始字段

| 字段 | 类型 | 用途 |
|---|---|---|
| `product_id` | integer | 商品身份 |
| `title` | text | 原始标题 |
| `sales_count` | integer | 销量 |
| `timestamp` | timestamp | 原始时间 |
| `user_id` | text | 示例来源记录标识 |
| `category` | text | 粗粒度类别 |
| `source` | text | 平台 |

### 4.2 字段流转

| 原始层 | 标准层 | 应用层 | 说明 |
|---|---|---|---|
| `product_id` | `product_id` | `product_id` | 保留商品身份 |
| `title` | `title` | 不保留 | 标准层保留原始标题 |
|  | `title_norm` | `title` | 应用层的 `title` 是归一化标题 |
| `sales_count` | `sales_count` | `sales_count` | 校验后求和 |
| `timestamp` | `"timestamp"` | 不保留 | 标准层转为 `timestamptz` |
|  | `business_date` | `stat_date` | 业务日期 |
| `user_id` | `user_id` | 不保留 | 只保留原始字段，不作为唯一键 |
| `category` | `category` | 不保留 | 小写化后作为 category gate |
| `source` | `source` | `source` | 直接作为平台字段 |
|  | `is_maxi_dress` | 不保留 | 只表示 explicit 命中 |

标准层只增加 3 个必要派生字段：

- `title_norm`：用于匹配和聚合的归一化标题；
- `business_date`：按业务时区生成的日期；
- `is_maxi_dress`：explicit 命中标记。

## 5. 表结构

### 5.1 原始层

```sql
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE raw.sales_data (
    product_id  bigint,
    title       text,
    sales_count integer,
    "timestamp" timestamp,
    user_id     text,
    category    text,
    source      text
);
```

原始层完全对应 Excel 的 7 个字段，不增加 `event_id`、fingerprint 等字段。

### 5.2 标准层

```sql
CREATE SCHEMA IF NOT EXISTS std;

CREATE TABLE std.sales_clean (
    product_id     bigint      NOT NULL,
    title          text        NOT NULL,
    sales_count    integer     NOT NULL CHECK (sales_count >= 0),
    "timestamp"    timestamptz NOT NULL,
    user_id        text,
    category       text        NOT NULL,
    source         text        NOT NULL,
    title_norm     text        NOT NULL CHECK (title_norm <> ''),
    business_date  date        NOT NULL,
    is_maxi_dress  boolean     NOT NULL DEFAULT false,

    CONSTRAINT uq_sales_clean_source UNIQUE NULLS NOT DISTINCT (
        product_id, title, sales_count, "timestamp",
        user_id, category, source
    )
);

CREATE INDEX ix_sales_clean_date_source
    ON std.sales_clean (business_date, source);

CREATE INDEX ix_sales_clean_maxi
    ON std.sales_clean (business_date, source, product_id)
    WHERE is_maxi_dress;
```

说明：

- 7 个原始字段全部保留；
- 新增 `title_norm`、`business_date`、`is_maxi_dress`；
- `uq_sales_clean_source` 让同一批样例重复执行时不会重复插入；
- 不创建异常记录表。原始层保留全部数据，ETL 将异常原因写入批次质量日志和监控指标。

### 5.3 应用层

应用层是“日期 + 平台 + 商品 + 归一化标题”的聚合表：

```sql
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.maxi_dress_daily (
    stat_date   date   NOT NULL,
    source      text   NOT NULL,
    product_id  bigint NOT NULL,
    title       text   NOT NULL, -- 归一化后的标题
    sales_count bigint NOT NULL CHECK (sales_count >= 0),
    PRIMARY KEY (stat_date, source, product_id, title)
) PARTITION BY RANGE (stat_date);
```

示例分区：

```sql
CREATE TABLE app.maxi_dress_daily_2024_01
    PARTITION OF app.maxi_dress_daily
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE app.maxi_dress_daily_2024_02
    PARTITION OF app.maxi_dress_daily
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

CREATE TABLE app.maxi_dress_daily_2024_03
    PARTITION OF app.maxi_dress_daily
    FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
```

应用层 grain 明确为 `stat_date + source + product_id + title`：

- `product_id` 防止不同商品因标题相同被错误合并；
- `title` 保存归一化标题，便于前端展示和标题级比较；
- 同一商品的不同标题变体会保留为不同行，不会直接丢失变体信息；
- 按日期和平台求和时，再对商品/标题行做聚合即可。

## 6. 归一化与 explicit 规则

### 6.1 共享归一化函数

归一化只保留一个事实源，放在数据库函数中，ETL 和接口参数校验都调用同一套规则。

```sql
CREATE OR REPLACE FUNCTION std.normalize_text(input text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
    SELECT trim(
        regexp_replace(
            regexp_replace(
                lower(replace(coalesce(input, ''), '''', '')),
                '[^a-z0-9]+', ' ', 'g'
            ),
            '\s+', ' ', 'g'
        )
    );
$$;

CREATE OR REPLACE FUNCTION std.normalize_title(input text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
    SELECT array_to_string(
        ARRAY(
            SELECT token
            FROM regexp_split_to_table(std.normalize_text(input), '\s+') AS token
            WHERE token <> ''
            ORDER BY token
        ),
        ' '
    );
$$;

CREATE OR REPLACE FUNCTION std.is_explicit_maxi_dress(
    p_title text,
    p_category text
)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
    SELECT lower(trim(coalesce(p_category, ''))) = 'dress'
       AND std.normalize_text(p_title) ~ '(^| )maxi( |$)'
       AND std.normalize_text(p_title) ~ '(^| )dress( |$)';
$$;
```

归一化示例：

```text
MAXI DRESS WHITE
→ dress maxi white

Women's Maxi-Dress Floral
→ dress floral maxi womens

Maxi Denim Dress
Denim Maxi Dress
→ denim dress maxi
```

### 6.2 分类规则

```text
category = dress
且 title_norm 含 maxi token
且 title_norm 含 dress token
    → is_maxi_dress = true

其他情况
    → is_maxi_dress = false
```

没有 synonym 规则，没有 extended 口径。

## 7. 标准层生成与幂等

```sql
WITH base AS (
    SELECT DISTINCT
        product_id,
        title,
        sales_count,
        "timestamp",
        user_id,
        lower(trim(category)) AS category,
        lower(trim(source)) AS source
    FROM raw.sales_data
),
normalized AS (
    SELECT
        product_id,
        title,
        sales_count,
        "timestamp" AT TIME ZONE 'Asia/Shanghai' AS occurred_at,
        user_id,
        category,
        source,
        std.normalize_title(title) AS title_norm
    FROM base
)
INSERT INTO std.sales_clean (
    product_id,
    title,
    sales_count,
    "timestamp",
    user_id,
    category,
    source,
    title_norm,
    business_date,
    is_maxi_dress
)
SELECT
    product_id,
    title,
    sales_count,
    occurred_at,
    user_id,
    category,
    source,
    title_norm,
    (occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS business_date,
    std.is_explicit_maxi_dress(title, category) AS is_maxi_dress
FROM normalized
WHERE sales_count >= 0
  AND product_id IS NOT NULL
  AND title IS NOT NULL
  AND title <> ''
  AND title_norm <> ''
  AND occurred_at IS NOT NULL
  AND category IS NOT NULL
  AND source IN ('website', 'app', 'marketplace')
ON CONFLICT ON CONSTRAINT uq_sales_clean_source DO NOTHING;
```

### 7.1 重复数据

样例阶段按原始 7 个字段判断完全重复：

- 300 条 → 去重后 288 条；
- 标准层的唯一约束保证同一批数据重复执行不会重复插入；
- 生产环境如果上游提供稳定 `source_event_id`，应优先使用它，而不是依赖全部字段比较。

`user_id` 不是唯一事件标识：样例中 300 行只有 105 个不同 `user_id`，因此不能作为主键。

### 7.2 时区

原始 `timestamp` 是没有时区的 naive datetime，本项目约定它表示 `Asia/Shanghai` 本地时间：

- 入库时转换为 `timestamptz`；
- `business_date` 按 `Asia/Shanghai` 生成；
- API 的 v1 `timezone` 只允许 `Asia/Shanghai`，其他值返回 `INVALID_TIMEZONE`；
- 测试覆盖 `2024-01-31 23:55`、`2024-02-01 00:05`、`2024-02-29 23:50`、`2024-03-01 00:10`。

### 7.3 异常记录

不新增异常表：

- 原始层保留全部来源记录，作为审计底稿；
- 标准层只写入通过校验的记录；
- ETL 在批次质量日志中记录 `raw_count`、`duplicate_count`、`rejected_count`、`accepted_count`、`reject_reason`；
- 异常不静默消失，但不会污染标准层和应用层；
- 样例数据没有异常记录，质量日志中 `rejected_count = 0`。

## 8. 应用层刷新

全量样例重建使用事务，不直接 `TRUNCATE` 在线服务表：

```sql
BEGIN;

DELETE FROM app.maxi_dress_daily
WHERE stat_date BETWEEN $1::date AND $2::date;

INSERT INTO app.maxi_dress_daily (
    stat_date,
    source,
    product_id,
    title,
    sales_count
)
SELECT
    business_date AS stat_date,
    source,
    product_id,
    title_norm AS title,
    sum(sales_count)::bigint AS sales_count
FROM std.sales_clean
WHERE is_maxi_dress = true
  AND business_date BETWEEN $1::date AND $2::date
GROUP BY business_date, source, product_id, title_norm
ON CONFLICT (stat_date, source, product_id, title)
DO UPDATE SET sales_count = EXCLUDED.sales_count;

COMMIT;
```

生产环境：

- 按受影响日期范围执行；
- 使用刷新锁避免同一日期被并发刷新；
- 大范围回填使用 staging table 或分区 attach/swap；
- `ON CONFLICT` 防止重复插入，`DELETE` 负责清理修正后消失的旧行。

## 9. 核心查询

### 9.1 日期 + 平台趋势

```sql
SELECT
    stat_date::text AS date,
    source          AS platform,
    sum(sales_count)::bigint AS sales_count
FROM app.maxi_dress_daily
WHERE stat_date BETWEEN $1::date AND $2::date
  AND source = ANY($3::text[])
GROUP BY stat_date, source
ORDER BY stat_date, source;
```

### 9.2 日期 + 平台 + 商品/标题下钻

```sql
SELECT
    stat_date::text AS date,
    source          AS platform,
    product_id,
    title,
    sum(sales_count)::bigint AS sales_count
FROM app.maxi_dress_daily
WHERE stat_date BETWEEN $1::date AND $2::date
  AND source = ANY($3::text[])
GROUP BY stat_date, source, product_id, title
ORDER BY stat_date, source, product_id, title;
```

日期 + 平台查询是默认接口；商品/标题明细是可选下钻，避免默认返回无界数据。

## 10. REST API

### 10.1 路径

```http
GET /v1/sales/trends
```

### 10.2 参数

| 参数 | 必填 | 示例 | 说明 |
|---|---|---|---|
| `category` | 否 | `maxi dress` | 默认值；先归一化再校验 |
| `start_date` | 是 | `2024-01-01` | 包含边界 |
| `end_date` | 是 | `2024-03-13` | 包含边界 |
| `platform` | 否 | `app&platform=website` | 可重复；不传则默认三个平台 |
| `granularity` | 否 | `day` | `day`、`week`、`month`、`auto` |
| `include_titles` | 否 | `false` | 是否返回商品/标题级明细 |
| `page_size` | 否 | `100` | 仅 `include_titles=true` 时生效，最大 500 |
| `fill_missing` | 否 | `true` | 是否补齐无数据的日期 × 平台组合为 0 |
| `timezone` | 否 | `Asia/Shanghai` | v1 只允许该值 |

范围约束：

- `day` 粒度按返回点数保护：`period_count × platform_count` 超过 `MAX_SERIES_POINTS`（默认 100000）返回 `422 RANGE_TOO_LARGE`，不再有固定 366 天上限；
- `auto` 粒度在 day/week/month 间按跨度粗化，用于长范围图表；
- `include_titles=true` 必须分页；
- 请求超时、响应大小和 `statement_timeout` 都有服务端限制；
- 请求进入后，`category` 先调用 `std.normalize_text` 归一化并校验是否为 `maxi dress`，平台先去空格、转小写和去重，再查询应用层。

### 10.3 请求示例

```http
GET /v1/sales/trends?category=maxi-dress&start_date=2024-01-01&end_date=2024-01-03&platform=app&platform=website
```

### 10.4 返回示例

```json
{
  "query": {
    "category": "maxi dress",
    "start_date": "2024-01-01",
    "end_date": "2024-01-03",
    "platforms": ["app", "website"],
    "granularity": "day",
    "timezone": "Asia/Shanghai",
    "fill_missing": true
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

`series` 是日期 × 平台聚合，补零行不包含商品和标题，因此不需要 `title:null`。

### 10.5 错误处理

| HTTP | code | 场景 |
|---|---|---|
| 400 | `INVALID_DATE_FORMAT` | 日期格式错误 |
| 400 | `INVALID_DATE_RANGE` | 开始日期晚于结束日期 |
| 400 | `UNSUPPORTED_CATEGORY` | 归一化后不是 maxi dress |
| 400 | `INVALID_PLATFORM` | 平台不在白名单 |
| 400 | `INVALID_TIMEZONE` | 时区不是 Asia/Shanghai |
| 422 | `RANGE_TOO_LARGE` | 日期范围或返回行数超过限制 |
| 503 | `DATABASE_UNAVAILABLE` | 数据库或只读副本不可用 |

> `429 RATE_LIMITED`（租户/IP 限流）为生产扩展，本 Demo 未实现，不列为已实现错误码。

## 11. 大数据量与高并发

1. 应用层按月 `stat_date` 分区，查询触发 partition pruning；
2. 主键 `(stat_date, source, product_id, title)` 覆盖趋势和商品下钻；
3. 标准层索引 `(business_date, source)`，maxi 部分索引 `(business_date, source, product_id)`；
4. 日期 × 平台聚合走预聚合表，标题级明细才访问更细粒度；
5. Redis 缓存日期 × 平台聚合结果，key 包含 API 版本、rule version、日期、平台、timezone、fill 参数；
6. 查询走只读副本，PgBouncer 复用连接；
7. 以 `statement_timeout`、最大返回行数、分页限制最坏情况（租户/IP 限流在生产环境再加）；
8. 近 13 个月热数据保留，更早标准层归档，应用层聚合继续保留；
9. 如果未来事件达到每天数千万到数亿级，再把标准层明细迁移到 ClickHouse；当前阶段不提前拆库。

## 12. 测试与验收

### 12.1 数据测试

- 原始 300 条；
- 完全重复 12 组；
- 去重后 288 条；
- explicit：119 条、1117 销量、12 个 product_id；
- 平台分布：app=368、marketplace=372、website=377；
- `Elegant Long Dress`、`Maxi Skirt`、`Summer Mini Dress` 不进入结果。

### 12.2 ETL 测试

- 同一批数据连续导入两次，标准层行数不变；
- 同一批数据连续刷新两次，应用层销量仍为 1117；
- `2024-01-31 23:55` 与 `2024-02-01 00:05` 落入正确业务日期；
- 异常数据只记录到质量日志，不进入标准层；
- 刷新失败时事务回滚，不留下半成品聚合。

### 12.3 API 测试

- 单平台、多平台查询；
- 不传平台时返回三个平台；
- `maxi-dress`、`MAXI  DRESS` 归一化后通过；
- `long dress` 返回 `UNSUPPORTED_CATEGORY`；
- `include_titles=false` 时只返回日期 × 平台聚合；
- `include_titles=true` 时分页并返回 `product_id + title`；
- 日期范围过大返回 `RANGE_TOO_LARGE`；
- 非 `Asia/Shanghai` 返回 `INVALID_TIMEZONE`。

### 12.4 性能验证

- `EXPLAIN (ANALYZE, BUFFERS)` 检查是否发生分区裁剪；
- 日期 × 平台查询结果行数上限约为 `日期数 × 平台数`；
- 记录缓存命中率、p50/p95/p99、错误率和数据库连接数；
- 压测场景至少覆盖并发 50/200/500。

## 13. 3 天开发计划

### Day 1

- 建原始层、标准层、应用层表；
- 导入 Excel；
- 实现归一化函数、唯一约束、explicit 分类；
- 核对 300/288/119/1117。

### Day 2

- 实现应用层分区和受影响日期刷新；
- 实现 FastAPI 参数预处理、日期范围校验、补零和错误处理；
- 完成日期 × 平台接口和可选标题下钻；
- 生成 Swagger 和示例请求。

### Day 3

- 加 Redis 缓存、只读副本配置和索引验证；
- 跑重复导入、时区、异常、API 和 `EXPLAIN` 测试；
- 写 README、架构图、数据质量对账说明；
- 录 demo，展示 explicit 口径、补零和错误处理。

## 14. 设计边界

- 本文档是架构和实现蓝图，不是最终可运行提交；
- 最终提交必须包含 ETL、FastAPI、SQL、测试和 README；
- 如果业务要求商品级归属，当前应用层已保留 `product_id`；
- 如果业务要求标题归并到统一商品名，需要额外定义标题到商品的 canonical mapping，但不属于本题 explicit 规则；
- 若真实数据源提供累计快照而非增量销量，必须先做 de-snapshot，不能直接求和。

## 15. Demo 已实现 vs 生产扩展

本仓库可运行 Demo 已实现：三层模型、explicit-only maxi dress 口径、标题归一化（SQL/Python 双实现）、月分区与分区裁剪、标准层索引、应用层预聚合、ETL 幂等与质量对账、事务式应用层刷新、coverage 预计算（`app.coverage_meta`）、`psycopg_pool` 连接池、按返回点数保护的日粒度范围、REST API 与错误 envelope、Docker Compose、单元/集成测试。

以下为生产扩展，Demo 未实现（仅在本文说明方案，不宣称已部署）：

- Redis 结果缓存、只读副本、PgBouncer 连接池、租户/IP 限流（`429 RATE_LIMITED`）。


