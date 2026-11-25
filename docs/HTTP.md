# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态；`decisions` 给出每份申请的最新复核结论。

`PATCH /api/runs/<id>` 接收 `revision`、`status`、`note`，可选 `cases`。状态使用 `APPROVED` 或 `HELD`。

- 不传 `cases`：整批应用同一结论。
- `cases` 为 `{"<申请号>": "APPROVED" | "HELD"}`：只判定列出的申请，其余申请保持既有结论。
- 所有申请均为 `APPROVED` 时批次状态为 `APPROVED`，否则为 `HELD`。

冲突返回 409，客户端读取新版本后重试：

| 代码 | 含义 |
|---|---|
| `STALE_REVIEW` | `revision` 落后于当前批次 |
| `RUN_FINALIZED` | 批次或该申请已签发 |
| `UNRESOLVED_ISSUES` | 申请不可签发（差异、暂缓或整批暂缓） |
| `STALE_MATERIAL` | 该申请材料已更正并生效，须按新版材料重新核算 |
