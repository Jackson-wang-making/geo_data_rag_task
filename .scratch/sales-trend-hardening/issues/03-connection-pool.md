# 03: Connection pool（psycopg_pool）

**What to build:** 用 `psycopg_pool.ConnectionPool` 替代逐次 `psycopg.connect`，单进程共享连接；保持惰性创建（无库可导入 app）与 `SET LOCAL statement_timeout`。

**Blocked by:** None

**Status:** done

- [x] `requirements.txt` 新增 `psycopg_pool`。
- [x] `PostgresSalesTrendRepository` 新增惰性 `_pool()`（`min_size=1, max_size=10, timeout=5`），`_fetchall` 从 pool 取连接。
- [x] 每连接仍 `SET LOCAL statement_timeout = '5000ms'`。
- [x] 测试注入 fake repository 的路径不受影响；无 `DATABASE_URL` 导入 app 不建 pool。
- [x] 新增 `UT-POOL-01..03`、`IT-POOL-01` 全部 PASS。
