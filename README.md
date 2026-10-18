# Shopping Agent

[![CI](https://github.com/david-dev666/shopping-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/david-dev666/shopping-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](backend/pyproject.toml)

**跨平台比价与购物决策 Agent。** 输入商品名或选购需求，汇总京东、淘宝、拼多多的候选报价，检查标题规格，按预算给出推荐与依据。

例如：`预算300元买小米手环9 NFC版`。

![结果页：固定样例，非实时报价](docs/img/results.jpg)

## 项目重点

- **检查规格，再比较报价**：展示品牌、代数、版本等标题依据，区分冲突、混卖和信息不足；明确冲突与混卖不作为首选。
- **可调整的选购流程**：修改预算、偏好和筛选条件，复用服务端候选快照更新推荐，无需重复采集；支持最多三件商品对比。
- **可追踪的 Agent**：展示实际执行进度、推荐理由与节点轨迹；预算由代码约束，模型不可用时可按规则降级。

当前重点覆盖手环代数与版本。标题一致不代表实际 SKU、优惠资格或最终成交价已核实。

## 快速开始

需要 Python 3.11+ 和 uv。

```bash
git clone https://github.com/david-dev666/shopping-agent.git
cd shopping-agent/backend
uv sync --extra dev
uv run uvicorn app.main:app --port 8000
```

打开 [本地页面](http://127.0.0.1:8000)，点击 **体验选购样例** 即可预览，无需密钥或扩展。样例来自固定快照，普通搜索请求真实数据，失败不会替换成样例。

真实查询与智能排序的配置见 [backend/.env.example](backend/.env.example)：

| 能力 | 配置 |
|---|---|
| 平台采集 | 安装 Kimi 浏览器扩展并登录目标平台；或填写联盟 API 凭据，已配置的 API 优先 |
| 模型决策 | 在 `backend/.env` 配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`；缺少模型时使用规则降级 |
| 存储 | 默认 SQLite，启动自动建表 |

直接比价可复用 5 分钟缓存，来源会明确标注；可点击“重新采集”跳过。Agent 查询目前不使用这层缓存。

## 如何工作

```text
需求解析 → 平台采集 → 标题核对 → 条件筛选 → 决策排序 → 推荐与依据
```

FastAPI 提供接口并托管原生 HTML / CSS / JS，LangGraph 编排流程，SQLite 保存报价、执行轨迹与候选快照。更新推荐只运行筛选后的决策流程；快照保留 24 小时，过期需重新查询。

## 已知限制

平台采集依赖可用数据源和登录态，可能返回空结果或要求验证；不绕过验证码，不自动下单。当前没有价格历史与盯价提醒。

下一步优先让 Agent **发现缺失信息后继续求证**：澄清关键需求、限量补查候选，再根据证据重新判断。这些能力尚未实现，任务清单见 [TODO](TODO.md)。

## 开发与文档

- [开发指南](docs/08-development.md)：测试、安装包、数据库迁移及目录说明。
- [标题证据与快照](docs/07-title-evidence.md)：推荐约束、接口契约和限制。
- [AI 辅助评测](backend/eval/README.md)：20 例历史样本、逐例理由和待确认项；非独立准确率。
- [当前进展](docs/05-status.md) · [架构设计](docs/02-architecture.md) · [界面验收](docs/06-ui-review.md)。

[MIT License](LICENSE)。浏览器采集使用 [Kimi 浏览器扩展](https://www.kimi.com/products/kimi-webbridge) 的本地 daemon。
