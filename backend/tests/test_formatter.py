"""Formatter 单元测试（plan §15 pytest）。"""
from app.config import settings
from app.tools.budget import TOOL_RESULT_TRUNCATED
from app.tools.formatter import (
    PREVIEW_MAX,
    format_count_result,
    format_find_result,
)


def test_find_format_basic_fields():
    r = format_find_result(
        collection="script_scene_summary",
        operation="find",
        purpose="查询第8场摘要",
        rows=[{"scene_no": 8, "summary": "戒指丢了"}],
    )
    assert r.full_result.startswith("MONGO_RESULT")
    assert "collection: script_scene_summary" in r.full_result
    assert "operation: find" in r.full_result
    assert "purpose: 查询第8场摘要" in r.full_result
    assert "row_count: 1" in r.full_result
    assert "truncated: false" in r.full_result
    assert "estimated_tokens:" in r.full_result
    assert r.truncated is False
    assert r.row_count == 1


def test_preview_max_200():
    rows = [{"scene_no": i, "summary": "内容" * 50} for i in range(20)]
    r = format_find_result(
        collection="script_scene_summary",
        operation="find",
        purpose="大量数据",
        rows=rows,
    )
    assert len(r.preview) <= PREVIEW_MAX


def test_chinese_json_not_escaped():
    r = format_find_result(
        collection="script_scene_summary",
        operation="find",
        purpose="中文",
        rows=[{"summary": "戒指"}],
    )
    assert "戒指" in r.full_result
    assert "\\u" not in r.full_result


def test_truncation_marker_and_notice():
    big = "原" * (settings.max_tool_chars + 5000)
    r = format_find_result(
        collection="script_scene_original",
        operation="find",
        purpose="查原文",
        rows=[{"content": big}],
    )
    # 注意：单字段超长会先被 [FIELD_TRUNCATED] 压到 8000，
    # 这里构造的字段超过 MAX_CONTENT_FIELD_CHARS 也超 tool chars
    assert r.full_result.startswith("MONGO_RESULT")
    assert "truncated: true" in r.full_result or r.field_truncated is True


def test_truncation_keeps_header_intact():
    # 构造多行使整体 body 超过 tool chars 上限触发 TOOL_RESULT_TRUNCATED
    rows = [{"scene_no": i, "summary": "内容" * 200} for i in range(100)]
    r = format_find_result(
        collection="script_scene_summary",
        operation="find",
        purpose="海量",
        rows=rows,
    )
    assert r.truncated is True
    # 头部结构完好：以 MONGO_RESULT 开头，含 truncation_reason
    assert r.full_result.startswith("MONGO_RESULT")
    assert "truncation_reason:" in r.full_result
    assert r.full_result.rstrip().endswith(TOOL_RESULT_TRUNCATED)


def test_count_format():
    r = format_count_result(
        collection="script_scene_original",
        operation="count",
        purpose="统计",
        count=42,
    )
    assert "operation: count" in r.full_result
    assert '"count": 42' in r.full_result
    assert r.truncated is False
