# 01: Unbounded day range（取消 366 天上限）

**What to build:** `GET /v1/sales/trends` 的 `granularity=day` 不再被 366 天硬上限拒绝；改为按返回点数 `period_count × platform_count` 保护，超限才 422 `RANGE_TOO_LARGE`。`auto` 的 day/week/month 粗化阈值保持不变。

**Blocked by:** None

**Status:** done

- [x] `_resolve_granularity` 新增 `platform_count` 入参；显式 `day` 分支改用 `MAX_SERIES_POINTS`（env 可配，默认 `100000`），移除该分支的 `DAY_MAX_DAYS` 判定。
- [x] `auto` 分支继续使用 `DAY_MAX_DAYS` / `AUTO_WEEK_MAX_DAYS`，行为不变。
- [x] `422 RANGE_TOO_LARGE` 的 `details` 提供 `max_points` 与 `requested_points`。
- [x] 更新 `tests/test_api.py` 中「day 跨 367 天 → 422」用例为 `200`，并新增一个真正超 `MAX_SERIES_POINTS` 的 422 用例。
- [x] 新增 `UT-RANGE-01..06` 测试全部 PASS。
