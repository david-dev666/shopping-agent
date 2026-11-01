# 工作流开发回归记录

- `llm.json`：真实 deepseek-chat，25 个场景、33 轮交互。
- `adversarial.json`：受控错误排序输出，25 个场景各三个顺序种子，共 75 次任务运行、99 轮交互。
- `llm_runner_snapshot.txt`：真实模型报告生成时的评测脚本源码，与报告中 `scripts/eval_workflow.py` 的哈希一致。当前脚本随后增加了注入模式引擎标签区分；真实模型执行路径相同。

数据集及生产 Agent 代码哈希记录在报告中。以上为开发回归记录，评测口径见 `docs/13-agent-evaluation.md`。在隔离副本中将脚本快照恢复到 `backend/scripts/eval_workflow.py` 可复现当时的执行版本；模型输出及耗时可能变化。
