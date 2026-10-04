# 准确率与耗时

两块都做成**可复现**的：评测口径、脚本、标注数据都在仓库里，照着命令就能跑出同样的表。

## 1. 相关性标注的准确率

匹配层是确定性规则（不依赖 LLM），产出「软标签」而非剔除。所以这里评测的是**规则打标的准确性**。

- 标注集：`backend/eval/rules_eval.jsonl`（36 条，覆盖型号 / 品牌 / 配件 / 二手）
- 脚本：`cd backend && uv run python scripts/eval_rules.py`（加 `--verbose` 打印判错用例）
- 口径：逐条标题预测命中的标签，按规则统计 precision / recall / F1，micro 为全部标签汇总

| 规则 | P | R | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| second_hand | 1.00 | 1.00 | 1.00 | 8 | 0 | 0 |
| rival | 1.00 | 1.00 | 1.00 | 4 | 0 | 0 |
| model_mismatch | 1.00 | 1.00 | 1.00 | 3 | 0 | 0 |
| off_brand | 1.00 | 1.00 | 1.00 | 3 | 0 | 0 |
| accessory | 0.80 | 0.80 | 0.80 | 4 | 1 | 1 |
| **micro** | **0.96** | **0.96** | **0.96** | 22 | 1 | 1 |

两个已知误判（都在 accessory）：

- 漏报：「小米手环9 保护壳 全包防摔 透明」——配件词落在标题中段，未触发「尾部配件」判定
- 误报：「小米手环9 礼盒装 全新 送表带」——赠送配件被当成配件商品

价格异常 / 销量偏低是**批次相对**规则（按全体中位数判定），不适用单条评测，由单元测试覆盖（`backend/tests/test_filter.py`）。评测集本身也进了 CI（`tests/test_eval.py`），指标回退会挂。

局限：标注集规模小（36 条）且为自建，绝对数值仅供参考，不代表线上分布；规格级同款匹配的准确率评估属路线图阶段 2。

## 2. 耗时

### 单平台采集（webbridge，本机实测）

命令：`cd backend && uv run python scripts/bench_crawl.py 小米手环9`

| 平台 | 耗时 | 说明 |
|---|---|---|
| 京东 | 1.5 – 3.9 s | 懒渲染，轮询到出数据 |
| 淘宝 | 2.1 – 2.7 s | 同上 |
| 拼多多 | 6 – 7 s | SSR 命中时 ≈1 s；无返回时走到 6 s 轮询上限 |

浏览器采集三平台共用单 tab 串行（`webbridge.py` 加锁），所以总采集时间取决于最慢的平台。

### Agent 端到端

一次 `POST /api/chat`（intent → research → match → filters → decide → recommend）本机实测 ≈ **15 s**，节点耗时：

| 节点 | 耗时 |
|---|---|
| research（三平台采集） | ≈ 11.1 s |
| decide（LLM 决策 + 全量排序） | ≈ 3.7 s |
| intent / match / filters / recommend | < 50 ms |

每个节点的耗时写进 trace（`elapsed_ms`），前端「执行轨迹」直接可见；未配置 LLM 时 `decide` 走确定性降级，几乎不耗时。

### 筛选重排

前端筛选面板点「重新筛选并排序」走 `POST /api/refine`（filters → decide → recommend，**跳过采集**），本机实测：

| 场景 | 耗时 |
|---|---|
| 30 条候选 → 筛选后 6 条并重新排序 | ≈ **2.0 s**（对比全量运行 ≈15 s） |

### 口径与影响因素

- 本机（macOS）实测，随网络与平台渲染波动，只作量级参考
- 采集耗时主要由**页面渲染等待**决定（`app/adapters/webbridge.py` 的 `PAGE_READY` 轮询策略），不是网络传输本身
- 联盟 API 数据源的耗时与 webbridge 不同，未计入上表
