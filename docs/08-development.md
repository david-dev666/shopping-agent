# 开发指南

在仓库根目录进入 `backend` 并执行 `uv sync --extra dev`。配置参考 [.env.example](../backend/.env.example)，接口文档在服务启动后的 `/docs`。

## 常用检查

以下命令在 backend 目录执行：

```bash
uv run pytest -q
uv run ruff check app tests scripts eval migrations
uv run python scripts/eval_rules.py
uv run python scripts/eval_pairs.py
uv run python scripts/bench_crawl.py 小米手环9
```

`bench_crawl.py` 会实际访问已配置的平台来源；默认 AI 评测不访问平台或模型。AI 评测的运行推荐选项、来源及局限见 [评测说明](../backend/eval/README.md)。

前端无需构建；Node.js 22+，在仓库根目录执行：

```bash
node --check backend/static/app.js
node --test frontend/tests/*.test.mjs
```

## 安装包验证

CI 构建 wheel，并在临时目录验证首页、静态资源、health、样例查询、快照重排和 SSE。在 backend 目录可复现：

```bash
uv build --wheel --out-dir /tmp/shopping-dist
uv pip install --no-deps --target /tmp/shopping-package /tmp/shopping-dist/*.whl
.venv/bin/python scripts/smoke_install.py --package-root /tmp/shopping-package
```

依赖使用当前环境，业务数据写入临时数据库，不调用平台或模型；结束后清理临时数据库。输出目录建议使用空目录。

## 数据库

默认 SQLite，启动自动建表。使用迁移记录版本：

```bash
uv run alembic upgrade head
```

`docker-compose.yml` 目前只启动 Postgres，不包含应用。切换时安装 `uv sync --extra postgres`，并设置 `DATABASE_URL`。

## 代码位置

| 路径 | 职责 |
|---|---|
| `backend/app/agents/` | 意图解析、决策、LangGraph 编排与轨迹 |
| `backend/app/adapters/` | 平台采集与浏览器来源 |
| `backend/app/matching/` | 标题证据、警示标签、筛选与排序约束 |
| `backend/app/storage/` | 报价、候选快照与轨迹存储 |
| `backend/static/` | 页面、样式和前端逻辑 |
| `backend/eval/` | 规则回归与 AI 弱标签案例 |
| `backend/tests/`、`frontend/tests/` | 后端与前端测试 |

[阶段总结](05-status.md) 记录当前交付；[TODO](../TODO.md) 为当前任务清单。[初始路线图](03-roadmap.md) 和 [早期指标](04-metrics.md) 保留历史设计与验证记录，不代表现有能力或线上性能。
