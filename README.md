# shopping-agent

输入一件商品，自动在京东 / 淘宝 / 拼多多三家问价，算出到手最低价，并给出购买入口。下单的最后一步由人确认。

跨平台比价 + 相关性过滤已可运行，LangGraph agent 编排开发中。

## 原则

- 不做自动下单、自动支付、自动退款
- 不绕过登录、验证码、访问控制
- 没有授权的数据源返回空结果，不用假数据填充
- 金额与阈值判断用确定性代码完成，不由 LLM 计算

## 工作方式

```
搜索词 → 三平台采集 → 相关性过滤（二手 / 竞品 / 配件）→ 到手价排序 → 购买入口
```

采集层每个平台一个 adapter，统一输出 `(platform, sku, title, price, coupon, ts)`：

- **官方联盟 API 优先**：京东联盟、淘宝客、多多进宝
- **浏览器采集兜底**：通过 [Kimi 浏览器扩展](https://www.kimi.com/products/kimi-webbridge) 的本地 daemon 驱动用户已登录的浏览器，无需申请任何 API key

匹配层目前为品牌级确定性过滤（二手 / 竞品 / 配件识别），规格级同款匹配与置信度评估在路线图阶段 2。

存储使用 SQLite：`offer` 表保存过滤前的全量报价，`crawl_log` 表记录每次抓取的成功 / 失败，便于排查数据缺失。

## 快速开始

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --port 8000
```

打开 http://127.0.0.1:8000 即可使用。

数据来源二选一：

1. **浏览器采集**（默认）：安装 Kimi 浏览器扩展，在浏览器中登录京东 / 淘宝 / 拼多多
2. **官方联盟 API**：在 `backend/.env` 中填入各平台 key（参考 `.env.example`），配置后优先于浏览器采集

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + Pydantic |
| 编排 | LangGraph（开发中）|
| 采集 | httpx（联盟 API）+ Kimi 浏览器扩展 daemon |
| 存储 | SQLite，正式版 Postgres |
| 前端 | 单文件 HTML 演示页，正式版 Next.js |

## 项目结构

```
shopping-agent/
├── docs/                     设计文档
├── backend/
│   ├── app/
│   │   ├── api/              HTTP 接口
│   │   ├── adapters/         平台采集适配器
│   │   ├── matching/         相关性过滤
│   │   ├── models/           数据模型
│   │   ├── agents/           LangGraph 编排（开发中）
│   │   └── storage/          持久化
│   ├── static/               演示页
│   └── tests/
├── docker-compose.yml
└── .env.example
```

## 文档

1. [docs/00-overview.md](docs/00-overview.md) 项目定位
2. [docs/01-landscape.md](docs/01-landscape.md) 竞品调研
3. [docs/02-architecture.md](docs/02-architecture.md) 架构设计
4. [docs/03-roadmap.md](docs/03-roadmap.md) 路线图
5. [docs/architecture.html](docs/architecture.html) Agent 架构说明（可视化网页）
