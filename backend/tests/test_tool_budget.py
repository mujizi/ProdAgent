"""Budget 单元测试（plan §15 pytest）。"""
from app.config import settings
from app.tools.budget import (
    FIELD_TRUNCATED,
    TOOL_RESULT_TRUNCATED,
    enforce_tool_budget,
    estimate_tokens,
    truncate_field,
    truncate_rows_fields,
)


def test_estimate_tokens_is_len_div_chars_per_token():
    text = "字" * 100
    assert estimate_tokens(text) == 100 // settings.chars_per_token


def test_estimate_tokens_min_one():
    assert estimate_tokens("") == 1


def test_small_body_not_truncated():
    body = "短内容"
    r = enforce_tool_budget(body)
    assert r.truncated is False
    assert r.text == body
    assert r.truncation_reason is None


def test_body_over_chars_truncated():
    # 超过 MAX_TOOL_CHARS 上限
    body = "x" * (settings.max_tool_chars + 5000)
    r = enforce_tool_budget(body)
    assert r.truncated is True
    assert r.text.endswith(TOOL_RESULT_TRUNCATED)
    assert r.truncation_reason == "tool_message_budget_exceeded"


def test_body_over_token_budget_truncated():
    # 构造仅超 token 预算但用 chars 上限同样会触发；这里验证截断后 token 不超太多
    hard_max_chars = min(
        settings.max_tool_chars,
        settings.max_tool_estimated_tokens * settings.chars_per_token,
    )
    body = "y" * (hard_max_chars + 1000)
    r = enforce_tool_budget(body)
    assert r.truncated is True
    # 截断后长度不超过 hard_max_chars
    assert len(r.text) <= hard_max_chars
    assert r.estimated_tokens <= settings.max_tool_estimated_tokens


def test_field_truncation_marker():
    big = "内" * (settings.max_content_field_chars + 100)
    val, truncated = truncate_field(big)
    assert truncated is True
    assert val.endswith(FIELD_TRUNCATED)
    assert len(val) <= settings.max_content_field_chars + len(FIELD_TRUNCATED) + 1


def test_field_not_truncated_when_small():
    val, truncated = truncate_field("小字段")
    assert truncated is False
    assert val == "小字段"


def test_truncate_rows_fields_flags():
    rows = [{"content": "内" * (settings.max_content_field_chars + 50), "n": 1}]
    new_rows, any_t = truncate_rows_fields(rows)
    assert any_t is True
    assert new_rows[0]["content"].endswith(FIELD_TRUNCATED)
    assert new_rows[0]["n"] == 1
