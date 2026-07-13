"""Tool Result 格式化（plan §9.4）。

把执行结果组装成给模型看的文本，并产出给前端 SSE 的元数据。
原文结果按完整场次装入预算，避免从 JSON 中间硬截断。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.budget import (
    enforce_tool_budget,
    estimate_tokens,
    tool_budget_max_chars,
    truncate_rows_fields,
)
from app.utils.json_utils import dumps

PREVIEW_MAX = 200
OUTLINE_COLLECTION = "seca_gen_scene_outline"

SOURCE_LABELS = {
    OUTLINE_COLLECTION: "剧本原文资料",
    "seca_element_type_detail": "人物与制片元素候选资料",
    "resolve_character_name": "人物名解析结果",
}

_OUTLINE_TRUNCATE_NOTICE = (
    "notice:\n"
    "结果未完整返回。不要基于当前结果做完整覆盖或否定性结论。\n"
    "查询剧本原文时，请按 next_scene_sort 使用更小的场次范围继续读取。"
)

_GENERIC_TRUNCATE_NOTICE = (
    "notice:\n"
    "结果已被硬截断。不要基于截断结果做过度推断；"
    "请拆分查询条件后重新读取。"
)


@dataclass
class FormattedResult:
    full_result: str
    preview: str
    row_count: int
    truncated: bool
    field_truncated: bool
    estimated_tokens: int
    estimated_tokens_before: int
    truncation_reason: str | None
    error_code: str | None = None
    payload: Any = None
    coverage: dict[str, Any] | None = None


def _preview(text: str) -> str:
    return text[:PREVIEW_MAX]


def _source_label(collection: str) -> str:
    return SOURCE_LABELS.get(collection, "剧本资料")


def _scene_sort(row: dict) -> int | None:
    value = row.get("scene_sort")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _group_outline_rows(rows: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for row in rows:
        scene_sort = _scene_sort(row)
        if groups and scene_sort is not None and _scene_sort(groups[-1][0]) == scene_sort:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def _format_outline_result(
    *,
    operation: str,
    purpose: str,
    rows: list[dict],
    requested_range: dict[str, int] | None,
    db_has_more: bool,
    db_next_scene_sort: int | None,
) -> FormattedResult:
    groups = _group_outline_rows(rows)
    included: list[dict] = []
    included_sorts: list[int] = []
    omitted_sorts: list[int] = []
    max_chars = tool_budget_max_chars()
    estimated_before = estimate_tokens(dumps(rows, indent=2))

    for index, group in enumerate(groups):
        candidate = [*included, *group]
        if len(dumps(candidate, indent=2)) > max_chars:
            omitted_sorts.extend(
                scene_sort
                for remaining in groups[index:]
                if (scene_sort := _scene_sort(remaining[0])) is not None
            )
            break
        included.extend(group)
        scene_sort = _scene_sort(group[0])
        if scene_sort is not None:
            included_sorts.append(scene_sort)

    formatter_has_more = len(included) < len(rows)
    oversized_scene = formatter_has_more and not included and bool(groups)
    has_more = formatter_has_more or db_has_more
    next_scene_sort = (
        None
        if oversized_scene
        else (omitted_sorts[0] if omitted_sorts else db_next_scene_sort)
    )
    coverage_complete = not has_more
    incomplete_reason = (
        "single_scene_exceeds_budget"
        if oversized_scene
        else (
            "scene_page_budget_exceeded"
            if formatter_has_more
            else ("query_limit_reached" if db_has_more else None)
        )
    )
    body = dumps(included, indent=2)
    estimated_after = estimate_tokens(body)
    coverage = {
        "requested_range": requested_range,
        "returned_scene_sorts": included_sorts,
        "omitted_scene_sorts": list(dict.fromkeys(omitted_sorts)),
        "has_more": has_more,
        "next_scene_sort": next_scene_sort,
        "coverage_complete": coverage_complete,
        "incomplete_reason": incomplete_reason,
    }

    header = (
        "资料查询结果\n"
        f"source: {_source_label(OUTLINE_COLLECTION)}\n"
        f"operation: {operation}\n"
        f"purpose: {purpose}\n"
        f"row_count_returned: {len(included)}\n"
        f"requested_range: {dumps(requested_range)}\n"
        f"returned_scene_sorts: {dumps(included_sorts)}\n"
        f"omitted_scene_sorts: {dumps(coverage['omitted_scene_sorts'])}\n"
        f"has_more: {str(has_more).lower()}\n"
        f"next_scene_sort: {next_scene_sort if next_scene_sort is not None else ''}\n"
        f"coverage_complete: {str(coverage_complete).lower()}\n"
        f"truncated: {str(has_more).lower()}\n"
        f"truncation_reason: {incomplete_reason or ''}\n"
        "field_truncated: false\n"
        f"estimated_tokens_before_truncate: {estimated_before}\n"
        f"estimated_tokens_after_truncate: {estimated_after}\n\n"
    )
    if has_more:
        header += f"{_OUTLINE_TRUNCATE_NOTICE}\n\n"
    full = header + "content:\n" + body
    return FormattedResult(
        full_result=full,
        preview=_preview(full),
        row_count=len(included),
        truncated=has_more,
        field_truncated=False,
        estimated_tokens=estimated_after,
        estimated_tokens_before=estimated_before,
        truncation_reason=incomplete_reason,
        payload=included,
        coverage=coverage,
    )


def format_find_result(
    *,
    collection: str,
    operation: str,
    purpose: str,
    rows: list[dict],
    requested_range: dict[str, int] | None = None,
    db_has_more: bool = False,
    db_next_scene_sort: int | None = None,
) -> FormattedResult:
    if collection == OUTLINE_COLLECTION:
        return _format_outline_result(
            operation=operation,
            purpose=purpose,
            rows=rows,
            requested_range=requested_range,
            db_has_more=db_has_more,
            db_next_scene_sort=db_next_scene_sort,
        )

    safe_rows, field_truncated = truncate_rows_fields(rows)
    body = dumps(safe_rows, indent=2)
    budget = enforce_tool_budget(body)

    if budget.truncated:
        header = (
            "资料查询结果\n"
            f"source: {_source_label(collection)}\n"
            f"operation: {operation}\n"
            f"purpose: {purpose}\n"
            f"row_count_returned: {len(safe_rows)}\n"
            "truncated: true\n"
            f"truncation_reason: {budget.truncation_reason}\n"
            f"estimated_tokens_before_truncate: {budget.estimated_tokens_before}\n"
            f"estimated_tokens_after_truncate: {budget.estimated_tokens}\n"
            f"field_truncated: {str(field_truncated).lower()}\n\n"
            f"{_GENERIC_TRUNCATE_NOTICE}\n\n"
            "content:\n"
        )
    else:
        header = (
            "资料查询结果\n"
            f"source: {_source_label(collection)}\n"
            f"operation: {operation}\n"
            f"purpose: {purpose}\n"
            f"row_count: {len(safe_rows)}\n"
            "truncated: false\n"
            f"field_truncated: {str(field_truncated).lower()}\n"
            f"estimated_tokens: {budget.estimated_tokens}\n\n"
        )
    full = header + budget.text
    return FormattedResult(
        full_result=full,
        preview=_preview(full),
        row_count=len(safe_rows),
        truncated=budget.truncated,
        field_truncated=field_truncated,
        estimated_tokens=budget.estimated_tokens,
        estimated_tokens_before=budget.estimated_tokens_before,
        truncation_reason=budget.truncation_reason,
        payload=safe_rows,
    )


def format_count_result(
    *, collection: str, operation: str, purpose: str, count: int,
) -> FormattedResult:
    payload = {"count": count}
    body = dumps(payload)
    full = (
        "资料查询结果\n"
        f"source: {_source_label(collection)}\n"
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
        payload=payload,
    )


def format_error_result(
    *, purpose: str, error: str, error_code: str = "query_failed",
    payload: dict[str, Any] | None = None,
) -> FormattedResult:
    full = (
        "资料查询结果\n"
        f"purpose: {purpose}\n"
        "error: true\n"
        f"error_code: {error_code}\n\n"
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
        error_code=error_code,
        payload=payload,
    )


def format_db_unavailable_result(*, purpose: str, error_code: str = "db_unavailable") -> FormattedResult:
    message = "剧本数据库暂时连接不上，可以稍后再试。"
    return format_error_result(
        purpose=purpose,
        error=message,
        error_code=error_code,
        payload={"message": message},
    )
