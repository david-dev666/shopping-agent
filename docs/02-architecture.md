# 架构设计

## 分层

```
                ┌─────────────────────────────┐
   用户输入  →  │  决策与执行层（LangGraph）  │
                └──────────────┬──────────────┘
                               │ 工具调用
                ┌──────────────┼──────────────┐
                ↓              ↓              ↓
          匹配层          存储层          采集层
        (同款对齐)     (价格时序)      (平台适配器)
```

采集层只管拿到数据并落库，不做判断。匹配层只管对齐同款，不做采集。决策层只管编排，不做采集与匹配的脏活。三层靠清晰接口隔开，任何一层都能单独测试。

## 一、采集层

每个平台一个 adapter，实现统一接口：

```python
class PlatformAdapter(Protocol):
    name: str

    async def search(self, query: str) -> list[RawOffer]: ...
    async def fetch(self, platform_id: str) -> RawOffer | None: ...
```

统一输出：

```text
RawOffer
  platform     平台标识
  platform_id  平台内商品 id
  title        标题原文
  price        当前价
  coupon       可用优惠
  url          商品链接
  ts           采集时间
```

采集策略优先级：

1. 官方联盟 API（京东联盟、多多进宝等）。结构化、合规，缺点是资质与审核
2. 页面内嵌结构化数据。优先读 JSON-LD，其次读页面里的接口返回
3. 浏览器渲染采集。需要登录或强动态时才用，且只采用户提交的链接

落库时同时写采集日志，记录成功、失败、耗时、失败原因。

## 二、匹配层

这是项目的核心难点，也是开源里的空白。

匹配分三级：

```text
一级  强标识匹配   型号、条形码、UPC 完全相同
二级  规格匹配     品牌 + 型号前缀 + 关键规格（容量、尺寸、版本）
三级  语义匹配     标题与图片的向量相似度，结合价格区间做过滤
```

输出结构：

```text
MatchResult
  group_id      同款分组 id
  offers        属于同一商品的各平台报价
  confidence    置信度 0 到 1
  evidence      命中依据，比如型号一致、条形码一致
  needs_review  低置信时置为 true，进入人工确认队列
```

置信度低于阈值的不参与比价结论，只作为候选展示。宁可少给结论，也不给错结论。

归一化处理必须做在匹配之前：品牌别名、型号大小写、单位换算、容量写法（256G / 256GB / 0.25T）。

## 三、存储层

核心表：

```text
product          同款商品分组，含规范名、品牌、型号、类别
offer            某平台上的一条报价，指向 product
price_history    (offer_id, date, price, coupon_price)，时序
match_review     待人工确认的匹配对
crawl_log        采集任务日志
```

价格历史是项目最重要的数据资产。同一个商品每天一条记录，长期累积才有价值。

初期允许 SQLite，正式版用 Postgres。表结构不变，只换连接串。

## 四、决策与执行层

用 LangGraph 编排，节点与工具分离。节点负责推理，工具负责确定性操作。

工具集：

```text
search_product(query)               搜索候选商品
resolve_match(offer_ids)            对齐同款，返回置信度
get_price_now(group_id)             各平台当前到手价
get_price_history(group_id, days)   历史价格曲线
estimate_deal(group_id)             是否好价，给出理由
build_purchase_links(group_id)      生成购买入口
```

图节点建议：

```text
intent        解析用户意图与约束（预算、品类、偏好）
research      调 search_product 找候选
match         调 resolve_match 对齐同款
price         调 get_price_now 与 get_price_history
decide        调 estimate_deal 判断是否值得买
recommend     汇总成结构化建议与购买入口
review        低置信或高风险时中断，等人工确认
```

关键设计点：

- 人工确认节点做成可中断、可恢复，用 LangGraph 的 checkpointer
- 每个节点输出结构化模型，用 Pydantic 校验，禁止 LLM 自由文本直出结论
- 金额比较、阈值判断、时间窗口全部由确定性代码完成，LLM 只负责理解与解释

## 五、可观测性

这是本项目相对现有开源的主要差异点，不要省。

每个节点记录：

```text
trace_id, node_name, input_digest, tool_calls, token_usage, cost, latency, output_digest
```

前端提供一个 trace 视图，能看到一次完整询问里每个节点调了什么工具、花了多少钱、为什么给出这个建议。

## 六、接口草案

```text
POST /api/query              自然语言询问，返回建议与 trace id
GET  /api/product/{group_id} 商品详情、当前价、历史曲线
GET  /api/trace/{trace_id}   一次询问的完整执行轨迹
POST /api/watch              添加盯价
GET  /api/watch              盯价列表与触发状态
```

## 七、待定项

- 目标平台最终选哪几个，取决于能否拿到联盟 API 资质
- 是否接受浏览器采集带来的合规与维护成本
- 匹配层的向量模型选型，先用现成 embedding，后期再考虑自训
- 前端是完整 Next.js 应用还是先做一个查询页
