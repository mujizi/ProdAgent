"""Formatter 单元测试（plan §15 pytest）。"""
import json

from app.config import settings
from app.tools.budget import TOOL_RESULT_TRUNCATED
from app.tools.formatter import PREVIEW_MAX, format_count_result, format_find_result


def _content_json(full_result: str):
    return json.loads(full_result.split("content:\n", 1)[1])


def test_find_format_basic_fields():
    r = format_find_result(
        collection="seca_gen_scene_outline",
        operation="find",
        purpose="查询第8场原文",
        rows=[{"scene_sort": 8, "scene_summary": "戒指丢了"}],
    )
    assert r.full_result.startswith("资料查询结果")
    assert "source: 剧本原文资料" in r.full_result
    assert "seca_gen_scene_outline" not in r.full_result
    assert "operation: find" in r.full_result
    assert "purpose: 查询第8场原文" in r.full_result
    assert "row_count_returned: 1" in r.full_result
    assert "truncated: false" in r.full_result
    assert r.truncated is False
    assert r.row_count == 1
    assert r.coverage["returned_scene_sorts"] == [8]
    assert r.coverage["coverage_complete"] is True


def test_preview_max_200():
    rows = [{"scene_sort": i, "scene_summary": "内容" * 50} for i in range(20)]
    r = format_find_result(
        collection="seca_gen_scene_outline", operation="find",
        purpose="大量数据", rows=rows,
    )
    assert len(r.preview) <= PREVIEW_MAX


def test_chinese_json_not_escaped():
    r = format_find_result(
        collection="seca_gen_scene_outline", operation="find",
        purpose="中文", rows=[{"scene_sort": 1, "scene_summary": "戒指"}],
    )
    assert "戒指" in r.full_result
    assert "\\u" not in r.full_result


def test_single_oversized_scene_is_not_marked_complete():
    big = "原" * (settings.max_tool_chars + 5000)
    r = format_find_result(
        collection="seca_gen_scene_outline", operation="find",
        purpose="查原文", rows=[{"scene_sort": 8, "content_text": big}],
    )
    assert r.truncated is True
    assert r.row_count == 0
    assert r.coverage["returned_scene_sorts"] == []
    assert r.coverage["omitted_scene_sorts"] == [8]
    assert r.coverage["next_scene_sort"] is None
    assert r.coverage["incomplete_reason"] == "single_scene_exceeds_budget"
    assert r.coverage["coverage_complete"] is False
    assert _content_json(r.full_result) == []


def test_outline_budget_keeps_complete_json_rows():
    rows = [{"scene_sort": i, "scene_summary": "内容" * 200} for i in range(1, 101)]
    r = format_find_result(
        collection="seca_gen_scene_outline", operation="find",
        purpose="海量", rows=rows,
    )
    returned = _content_json(r.full_result)
    assert r.truncated is True
    assert r.full_result.startswith("资料查询结果")
    assert "truncation_reason: scene_page_budget_exceeded" in r.full_result
    assert TOOL_RESULT_TRUNCATED not in r.full_result
    assert len(returned) == r.row_count
    assert [row["scene_sort"] for row in returned] == r.coverage["returned_scene_sorts"]
    assert r.coverage["omitted_scene_sorts"][0] == r.coverage["next_scene_sort"]


def test_outline_keeps_duplicate_scene_documents_together():
    rows = [
        {"scene_sort": 1, "content_text": "甲" * 1000},
        {"scene_sort": 2, "content_text": "乙" * 2500},
        {"scene_sort": 2, "content_text": "丙" * 2500},
        {"scene_sort": 3, "content_text": "丁" * 1000},
    ]
    r = format_find_result(
        collection="seca_gen_scene_outline", operation="find",
        purpose="按场分页", rows=rows,
    )
    returned_sorts = [row["scene_sort"] for row in _content_json(r.full_result)]
    assert returned_sorts.count(2) in {0, 2}
    assert 2 not in r.coverage["returned_scene_sorts"] or returned_sorts.count(2) == 2


def test_non_outline_keeps_legacy_truncation_marker():
    rows = [{"element_name": str(i), "remark": "内容" * 200} for i in range(100)]
    r = format_find_result(
        collection="seca_element_type_detail", operation="find",
        purpose="海量候选", rows=rows,
    )
    assert r.truncated is True
    assert r.full_result.rstrip().endswith(TOOL_RESULT_TRUNCATED)


def test_count_format():
    r = format_count_result(
        collection="seca_element_type_detail", operation="count",
        purpose="统计", count=42,
    )
    assert "operation: count" in r.full_result
    assert '"count": 42' in r.full_result
    assert r.payload == {"count": 42}
    assert r.truncated is False
