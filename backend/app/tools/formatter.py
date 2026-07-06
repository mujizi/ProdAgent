"""Tool Result 格式化（plan §9.4）。

把执行结果组装成给模型看的文本，并产出给前端 SSE 的元数据。

格式（截断只切尾部 content，前面的结构永不破坏）：

    MONGO_RESULT
    collection: ...
    operation: ...
    purpose: ...
    row_count: N
    truncated: false
    estimated_tokens: 320

    <JSON 内容>

截断时附 notice，并在尾部 content 处加 [TOOL_RESULT_TRUNCATED]。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.tools.budget import (
    enforce_tool_budget,
    estimate_tokens,
    truncate_rows_fields,
)
from app.utils.json_utils import dumps

PREVIEW_MAX = 200

_TRUNCATE_NOTICE = (
    "notice:\n"
    "结果已被硬截断。不要基于截断结果做过度推断。\n"
    "如需更准确细节，请重新调用 execute_mongo_query，"
    "用更具体的 scene_no/人物/地点/关键词缩小范围。"
)


@dataclass
class FormattedResult:
    full_result: str          # 给模型的完整工具消息文本
    preview: str              # 前 200 字（给前端）
    row_count: int
    truncated: bool
    field_truncated: bool
    estimated_tokens: int
    estimated_tokens_before: int
    truncation_reason: str | None


def _preview(text: str) -> str:
    return text[:PREVIEW_MAX]


def format_find_result(
    *,
    collection: str,
    operation: str,
    purpose: str,
    rows: list[dict],
) -> FormattedResult:
    # 1. 大字段截断
    rows, field_truncated = truncate_rows_fields(rows)
    row_count = len(rows)

    # 2. body = JSON 内容（放尾部，可被整体截断）
    body = dumps(rows, indent=2)
    budget = enforce_tool_budget(body)

    # 3. 组装头部（结构性，永不截断）
    if budget.truncated:
        header = (
            "MONGO_RESULT\n"
            f"collection: {collection}\n"
            f"operation: {operation}\n"
            f"purpose: {purpose}\n"
            f"row_count_returned: {row_count}\n"
            "truncated: true\n"
            f"truncation_reason: {budget.truncation_reason}\n"
            f"estimated_tokens_before_truncate: {budget.estimated_tokens_before}\n"
            f"estimated_tokens_after_truncate: {budget.estimated_tokens}\n"
            f"field_truncated: {str(field_truncated).lower()}\n\n"
            f"{_TRUNCATE_NOTICE}\n\n"
            "content:\n"
        )
        full = header + budget.text
    else:
        header = (
            "MONGO_RESULT\n"
            f"collection: {collection}\n"
            f"operation: {operation}\n"
            f"purpose: {purpose}\n"
            f"row_count: {row_count}\n"
            "truncated: false\n"
            f"field_truncated: {str(field_truncated).lower()}\n"
            f"estimated_tokens: {budget.estimated_tokens}\n\n"
        )
        full = header + budget.text

    return FormattedResult(
        full_result=full,
        preview=_preview(full),
        row_count=row_count,
        truncated=budget.truncated,
        field_truncated=field_truncated,
        estimated_tokens=budget.estimated_tokens,
        estimated_tokens_before=budget.estimated_tokens_before,
        truncation_reason=budget.truncation_reason,
    )


def format_count_result(
    *,
    collection: str,
    operation: str,
    purpose: str,
    count: int,
) -> FormattedResult:
    body = dumps({"count": count})
    full = (
        "MONGO_RESULT\n"
        f"collection: {collection}\n"
        f"operation: {operation}\n"
        f"purpose: {purpose}\n"
        "row_count: 1\n"
        "truncated: false\n"
        f"estimated_tokens: {estimate_tokens(body)}\n\n"
        f"{body}\n"
    )
    return FormattedResult(
        full_result=full,
        preview=_preview(full),
        row_count=1,
        truncated=False,
        field_truncated=False,
        estimated_tokens=estimate_tokens(body),
        estimated_tokens_before=estimate_tokens(body),
        truncation_reason=None,
    )


def format_error_result(*, purpose: str, error: str) -> FormattedResult:
    full = (
        "MONGO_RESULT\n"
        f"purpose: {purpose}\n"
        "error: true\n\n"
        f"{error}\n"
    )
    return FormattedResult(
        full_result=full,
        preview=_preview(full),
        row_count=0,
        truncated=False,
        field_truncated=False,
        estimated_tokens=estimate_tokens(full),
        estimated_tokens_before=estimate_tokens(full),
        truncation_reason=None,
    )
