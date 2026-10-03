# 竞品调研

调研时间：2026-09-29。数据取自 GitHub 仓库页面与 topic 聚合页，star 与 commit 数为页面显示值。

## 价格追踪类

| 项目 | star | 技术栈 | 说明 |
|---|---|---|---|
| `jez500/pricebuddy` | 约 1.1k | PHP + Laravel | 自托管价格追踪，粘贴 URL 定时抓取，多通道通知，Docker 部署 |
| `bulletinmybeard/price-scout` | 较少 | Python + DuckDB | 本地数据存储，内置价格趋势与历史分析 |
| `aloglu/centsible` | 较少 | 自托管 | 多网站价格监控，采集稳定性做得细 |
| `jqrzixin/Price-monitor` | 较少 | Python | 京东价格监控，低于预期价发邮件 |
| `willylam2222-bot/priceprobe` | 较少 | 单文件 Python | 零依赖，MIT，适合快速读懂全链路 |

共同点：采集与存储成熟，但基本是粘贴 URL 追踪单商品，没有跨平台同款匹配层。

## AI shopping agent 类

| 项目 | star | fork | commits | 时间 | 许可 |
|---|---|---|---|---|---|
| `Fujin1997/shopping-guide-agent` | 4 | 0 | 24 | 2026-07 起，最近 2026-08-30 | 未声明 |
| `frieren-123/shopping-agent-ai` | 23 | 4 | 4 | 2025-12-03 一天提交完 | MIT |
| `NayanaReddyK/AI_Shoppping_Agent` | 1 | 0 | 7 | 未取到 | 未声明 |

- `shopping-guide-agent`：LangGraph + FastAPI + Vue3，节点为 research → sentiment → advisor，接 Tavily 搜索，输出结构化报告。比价依赖 LLM 综合搜索摘要，没有真实价格沉淀
- `shopping-agent-ai`：Playwright 抓京东/淘宝/唯品会，配 OCR 绕过反爬，Streamlit 界面。提交全部集中在一天，之后未更新
- `AI_Shoppping_Agent`：面向印度电商，FastAPI + MCP + Groq + Gemini，含中位数异常值过滤与 1 小时缓存

## topic 下的重点项目

`cinderline/northcinder`
- 1.2k star，10 fork，仅 6 次提交，MIT
- 整个 `shopping-agent` topic 的绝对头部，第二名才 33 star
- 开源 MCP 服务器，跨商家比价，购买前必须请求一次性授权
- 排名逻辑本地可复跑，赞助不影响排名，审计日志留在本机
- 适配器覆盖 Shopify、WooCommerce、eBay、Etsy 与只读的 Amazon 比价
- 信号：6 次提交就能拿 1.2k star，说明赛道关注度远大于现有供给

`biheto/valusee`
- 33 star，0 fork，175 次提交，MIT，更新活跃
- 功能规划与本项目高度重合：商品识别 → SKU 同款匹配 → 跨平台到手价核算 → 评论风险分析 → 个性化建议 → 目标价监控 → 保价/退货/保修
- 后端 FastAPI + LangGraph，拆 11 个 agent 角色，含 Supervisor 与 Monitor
- 基础设施很重：Postgres + Redis + RabbitMQ + R2
- 首期只做手机、笔记本、显示器、耳机、键盘、路由器、扫地机器人、咖啡机
- 主动划定的边界值得直接抄：
  - 不自动下单、不支付、不退款
  - 不把大规模后台爬虫作为核心数据来源，改用浏览器扩展只读当前页面
  - 没授权的数据源返回空，不用假数据填充
  - 金额、时间由确定性代码校验，禁止 LLM 算钱
  - 登录价、验证码一律不绕
  - 采集需两次确认后才进入可信价格历史

`nolpak14/agorio`
- 15 star，TypeScript，基于 UCP 与 ACP 协议构建 AI 商务 agent 的工具包
- 如果想让项目带协议层技术含量，可以翻一下

## 结论

1. 空位不在再做一个比价，而在价格历史 + 决策闭环 + 可观测的 agent 编排
2. `northcinder` 验证了跨平台比价 + 人工确认购买这个形态有真实需求
3. `valusee` 验证了完整链路怎么做，但它做得太重，个人做不动
4. 本项目的差异化：反过来做轻做透，聚焦型号标准化品类，把价格历史沉淀和 agent 可观测性做扎实
