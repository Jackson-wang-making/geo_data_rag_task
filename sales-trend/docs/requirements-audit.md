# 第一题数据工程需求验收报告

> 对照文件：`../../inputs/exam/万悉科技AI数据工程师笔试题.md` 第一题  
> 实现目录：`sales-trend/`  
> 验收方式：代码审查 + 单元测试 + Docker PostgreSQL 集成测试 + API 实际请求

## 总体结论

**功能需求：基本全部达到；生产级高并发：设计说明达到，Demo 未部署全部生产能力。**

项目已经从“文字方案”变成可运行项目：

- 可以导入样例 Excel；
- 可以重复执行 ETL 不重复计数；
- 可以查询日期范围、一个或多个平台；
- 应用层保留归一化标题和 `product_id`；
- 可以返回日期 × 平台汇总和可选标题明细；
- Docker Compose 可以启动 PostgreSQL + ETL + FastAPI；
- 有单元测试、PostgreSQL 集成测试和 README。

## 逐项验收

| 题目要求 | 结论 | 实现与证据 |
|---|---|---|
| 返回 maxi dress 相关商品的日销量趋势 | PASS | `app/api/routes.py:14-58`；`app/services/sales_trends.py:153-270`；实际 API 返回 `total_sales=42` |
| 支持 start_date/end_date | PASS | `app/api/routes.py:26-27`；`app/services/sales_trends.py:180-187`；日期包含边界 |
| 支持一个或多个平台 | PASS | `app/api/routes.py:29-32`；`_normalize_platforms` 支持重复参数、去重和白名单校验 |
| maxi dress 识别/归一化规则 | PASS | `sql/002_functions.sql:3-49`；`sql/004_standardize.sql:1-60`；explicit-only 规则明确 |
| category 不能直接等于 dress | PASS | `std.is_explicit_maxi_dress()` 使用 category gate + maxi/dress token；`Maxi Skirt` 被排除 |
| 选择数据库并设计 schema | PASS | PostgreSQL 16；`sql/001_schema.sql:1-52`；`docs/architecture.md` |
| mapping/字段设计 | PASS | `README.md:260-290`；`docs/architecture.md` 字段映射章节 |
| 索引结构 | PASS | `sql/001_schema.sql:38-42`；应用层复合主键 `sql/001_schema.sql:45-52` |
| 核心 SQL | PASS | `sql/002_functions.sql:78-135`；`sql/004_standardize.sql`；`app/repository.py:130-220` |
| 至少按日期、平台分组 | PASS | `app/repository.py:130-155`；API 实际响应包含日期 × 平台 series |
| RESTful API 路径和参数 | PASS | `GET /v1/sales/trends`，`app/api/routes.py:11-58` |
| typical response | PASS | `app/models.py`；README 有完整 JSON 示例 |
| 必要错误处理 | PASS | `app/errors.py`；`app/main.py` 统一错误 envelope；`tests/test_api.py` 覆盖错误路径 |
| 大数据量优化说明 | PASS | `docs/architecture.md`；预聚合、月分区、索引、Redis、PgBouncer、读副本、ClickHouse 取舍 |
| 高并发实现程度 | PARTIAL | 预聚合、分区、索引已实现；Redis、只读副本、PgBouncer 只在设计说明中，Demo 未部署 |
| 任意日期范围 | PARTIAL | `start/end` 支持任意值；`day` 粒度限制 366 天，超过后可改用 week/month/auto，若要求“任意范围始终日粒度”则不满足 |
| 重复数据处理 | PASS | `etl/loader.py:180-213` 幂等原始导入；`sql/001_schema.sql:30-36` 唯一约束；`sql/004_standardize.sql:60` 幂等标准层 |
| 标题归一化 | PASS | `app/normalization.py`、`sql/002_functions.sql`；token 排序；SQL/Python parity integration test |
| timestamp/时区 | PASS | naive timestamp 按 `Asia/Shanghai` 解释；`business_date` 生成；边界测试覆盖 |
| 异常记录处理 | PASS | 无异常表；原始层保留全部数据，ETL 质量指标记录 rejected_count/reject_reasons；`quality.py` 有拒绝规则 |
| 设计说明/schema/查询/API/性能/质量/README | PASS | `sales-trend/docs/architecture.md`、`README.md`、`sql/` |
| 代码直接提交且尽量可运行 | PASS | Docker Compose、ETL CLI、FastAPI、测试完整 |
| 工程结构/可维护性 | PASS | `app/`、`etl/`、`sql/`、`tests/`、`docs/` 分层 |
| 技术判断可解释 | PASS | README 和架构文档说明了 PostgreSQL、预聚合、分区、缓存、ClickHouse 取舍 |

## 实际验证结果

### 数据

```text
raw=300
clean=288
explicit_rows=119
explicit_sales=1117
products=12
app_rows=118
app_sales=1117
```

### 幂等

重复执行 ETL：

```text
raw_rows_inserted=0
app_sales=1117
```

### API

```text
GET /v1/sales/trends?start_date=2024-01-01&end_date=2024-01-03&platform=app&platform=website
app=23
website=19
total_sales=42
coverage_max=2024-03-13
```

### 测试

```text
Docker: 34 passed
Local: 32 passed, 2 skipped（无 DATABASE_URL 时跳过集成测试）
```

### 分区

`EXPLAIN (ANALYZE, BUFFERS)` 只扫描 `app.maxi_dress_daily_2024_01`，分区裁剪有效。

## 需要改进但不阻塞本任务的两点

1. **任意日期范围**：当前默认 `day` 粒度最多 366 天；更长范围需要 `week/month/auto`。如果面试要求“任何跨度都必须能按日返回”，需要改成更大的上限或分页。
2. **高并发生产化**：当前代码验证了预聚合和分区，但没有实际启动 Redis、PgBouncer 和只读副本；这些已在架构文档中说明，Demo 不声称已达到生产 QPS。

## 最终判断

**可以作为第一题数据工程笔试项目提交。**

前提是：提交时明确说明这是“可运行 Demo”，高并发中的 Redis/读副本/PgBouncer 属于生产扩展，不把它描述成已经实际部署的能力。
