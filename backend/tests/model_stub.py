"""A scripted unit-test double; never used by the application or real-model evaluation."""

import json
import re
from types import SimpleNamespace


class ScriptedModel:
    def invoke(self, prompt):
        if "一次完成两件事" not in prompt and "商品列表（下标" not in prompt:
            from app.agents.graph import explicit_budget

            query = prompt.rsplit("用户需求：", 1)[-1].strip()
            return SimpleNamespace(content=json.dumps({
                "product": query, "budget": explicit_budget(query), "preference": "",
            }))
        rows = re.findall(r"^(\d+) \| (.*)$", prompt, re.M)
        shop_first = bool(re.search(r"选购偏好：[^\n]*(自营|旗舰)", prompt))
        ordered = sorted(rows, key=lambda row: (
            not any(x in row[1] for x in ("自营", "旗舰")) if shop_first else False,
            float(re.search(r"¥([\d.]+)", row[1])[1]),
        ))
        return SimpleNamespace(content=json.dumps({
            "worth": "wait", "confidence": 50, "reason": "测试模型输出",
            "summary": "测试输出", "items": [
                {"index": int(index), "score": 100 - n, "reason": "测试模型排序"}
                for n, (index, _) in enumerate(ordered)
            ],
        }))
