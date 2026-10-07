# 阶段性总结（2026-10-07）

## 已完成

| 层 | 状态 |
|---|---|
| 采集 | 三平台 adapter；联盟 API 优先 + Kimi 浏览器 daemon 兜底；单 tab 串行；滑块不绕过 |
| 标注 | 七条确定性规则打软标签、零剔除；`apply_tag_guard` 打标项排序降级；标签透传 LLM |
| 编排 | LangGraph 双入口：`intent→research→match→filters→decide→recommend` / `filters→decide→recommend`；每节点 trace 含 `elapsed_ms` |
| 接口 | `/api/query`、`/api/chat`、`/api/refine`、`/api/rank`、`/api/feedback`、`/api/trace/{id}` |
| 前端 | 比价 / Agent 双模式 + 筛选面板（平台 / 规格 / 标签 / 价格）+ 重新筛选排序 + 轨迹回放 |
| 工程化 | MIT、CI（ruff + pytest）、58 个测试、规则评测（micro F1 0.96）、采集耗时基准、DEMO_MODE、真实截图 |

## 还差什么

| 缺口 | 影响 | 阶段 |
|---|---|---|
| 价格历史曲线与时序沉淀 | 核心数据资产缺位，只能看当前时点 | 1 |
| 盯价与提醒 | 无持续价值闭环 | 4 |
| 规格级同款匹配 + 置信度 | 跨品牌 / 跨代同款对不上 | 2 |
| 人工确认中断与恢复 | 低置信结果无人工队列 | 3 |
| 一键部署（Dockerfile） | compose 只有 Postgres，无 app 服务 | 5 |
| 前端自动化测试 | 前端改动只能手测 | 5 |
| PDD 采集稳定性 | 实测常返回 0 条（平台风控） | — |

待决策：`offer` 表按设计只存**过滤前**原始报价，`tags` 未落库；若需要按标签做历史查询，需新增落库字段。

## 已知限制

见 [README](../README.md#已知限制) 与 [04-metrics.md](04-metrics.md)。
