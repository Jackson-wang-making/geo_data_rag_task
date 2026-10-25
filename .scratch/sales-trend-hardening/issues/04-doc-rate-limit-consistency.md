# 04: Doc consistency — 429 RATE_LIMITED 与实现对齐

**What to build:** 校验并确保 `architecture.md` / `README.md` 不再把 `429 RATE_LIMITED`（限流）表述为已实现，明确标注为生产扩展。

**Blocked by:** None（文档已部分修正，本 ticket 负责校验与复检）

**Status:** done

- [x] `architecture.md` 错误码表不含 `429 RATE_LIMITED`，或在表外标注「生产扩展，Demo 未实现」。
- [x] `architecture.md` §11 的「限流」措辞不再暗示已实现。
- [x] `architecture.md` §15 明确列出未实现的生产扩展（Redis/读副本/PgBouncer/限流），并将连接池/coverage 预计算/点上限移入已实现清单。
- [x] `README.md` 错误码表与实现一致（无 429 或标注生产扩展）。
- [x] `CHK-DOC-01..03` 校验通过。
