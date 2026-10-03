from app.agents.llm_utils import extract_json, invoke_json


class FakeLLM:
    """按脚本顺序返回内容的假 LLM。"""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[str] = []

    def invoke(self, prompt: str):
        self.calls.append(prompt)
        return type("Msg", (), {"content": self.replies.pop(0)})()


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_wrapped() -> None:
    text = '好的，以下是结果：\n```json\n{"a": 2}\n```\n希望有帮助'
    assert extract_json(text) == {"a": 2}


def test_extract_json_with_prose() -> None:
    assert extract_json('前置说明 {"a": 3} 后置补充') == {"a": 3}


def test_extract_json_no_json_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        extract_json("完全不是 JSON")


def test_invoke_json_success_first_try() -> None:
    llm = FakeLLM(['{"ok": 1}'])
    assert invoke_json(llm, "p") == {"ok": 1}
    assert len(llm.calls) == 1


def test_invoke_json_retries_then_succeeds() -> None:
    llm = FakeLLM(["不是 json", '{"ok": 2}'])
    assert invoke_json(llm, "p", retries=2) == {"ok": 2}
    assert len(llm.calls) == 2
    # 重试时追加了纠错指令
    assert "无法解析" in llm.calls[1]


def test_invoke_json_fallback_after_retries() -> None:
    llm = FakeLLM(["坏", "也坏", "还是坏"])
    fb = {"degraded": True}
    assert invoke_json(llm, "p", retries=2, fallback=fb) == fb
    assert len(llm.calls) == 3


def test_invoke_json_no_fallback_raises() -> None:
    import pytest

    llm = FakeLLM(["坏"])
    with pytest.raises((ValueError, Exception)):
        invoke_json(llm, "p", retries=0)
