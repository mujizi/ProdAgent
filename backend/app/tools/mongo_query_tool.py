"""execute_mongo_query：同步执行只读 Mongo 查询（plan §8/§9/§12）。

流程：Guard 校验+规范化 → pymongo find/count（maxTimeMS）→ Formatter（含截断）。
纯同步，调用方用 run_in_threadpool 包裹，避免阻塞事件循环。
返回 FormattedResult（含给模型的 full_result 与给前端的 preview/元数据）。
"""
from __future__ import annotations

import time

from app.config import settings
from app.db.mongo_client import get_db
from app.logging_config import get_logger
from app.tools.formatter import (
    FormattedResult,
    format_count_result,
    format_error_result,
    format_find_result,
)
from app.tools.mongo_guard import GuardError, validate_and_normalize

_log = get_logger("tool")

OUTLINE_COLLECTION = "seca_gen_scene_outline"


def _join_contents(contents) -> str:
    """把 outline 的 contents: [{type, content}, ...] 拼成单段原文。"""
    if not isinstance(contents, list):
        return ""
    parts = []
    for item in contents:
        if isinstance(item, dict):
            c = item.get("content")
            if c:
                parts.append(str(c))
    return "\n".join(parts)


def _postprocess_outline_rows(rows: list[dict]) -> list[dict]:
    """把每行的 contents 数组替换为拼接后的 content_text 字符串。"""
    out = []
    for row in rows:
        if isinstance(row, dict) and "contents" in row:
            new_row = {k: v for k, v in row.items() if k != "contents"}
            new_row["content_text"] = _join_contents(row.get("contents"))
            out.append(new_row)
        else:
            out.append(row)
    return out


def _to_mongo_projection(collection: str, projection: dict | None) -> dict | None:
    """发给 Mongo 的 projection：outline 的 content_text 是派生字段，需映射回 contents。"""
    if not projection or collection != OUTLINE_COLLECTION:
        return projection
    if "content_text" in projection:
        mp = {k: v for k, v in projection.items() if k != "content_text"}
        mp["contents"] = projection["content_text"]
        return mp
    return projection


def execute_mongo_query(script_id: str, args: dict) -> FormattedResult:
    purpose = args.get("purpose", "")
    t0 = time.time()

    # 1. Guard
    try:
        safe = validate_and_normalize(script_id, args)
    except GuardError as e:
        _log.warning(
            f"tool_guard_reject purpose={purpose!r} reason={e} "
            f"collection={args.get('collection')!r} operation={args.get('operation')!r}"
        )
        return format_error_result(purpose=purpose, error=f"查询被拒绝：{e}")

    collection = safe["collection"]
    operation = safe["operation"]
    limit_requested = args.get("limit")
    _log.info(
        f"tool_call_start collection={collection} operation={operation} "
        f"purpose={purpose!r} limit_requested={limit_requested} limit_final={safe['limit']}"
    )

    # 2. 执行
    try:
        coll = get_db()[collection]
        if operation == "count":
            count = coll.count_documents(
                safe["filter"], maxTimeMS=settings.mongo_max_time_ms
            )
            result = format_count_result(
                collection=collection, operation=operation,
                purpose=purpose, count=count,
            )
            row_count = 1
        else:  # find
            mongo_projection = _to_mongo_projection(collection, safe["projection"])
            cursor = coll.find(
                safe["filter"],
                mongo_projection,
                limit=safe["limit"],
                max_time_ms=settings.mongo_max_time_ms,
            )
            if safe.get("sort"):
                cursor = cursor.sort(list(safe["sort"].items()))
            rows = list(cursor)
            if collection == OUTLINE_COLLECTION:
                rows = _postprocess_outline_rows(rows)
            result = format_find_result(
                collection=collection, operation=operation,
                purpose=purpose, rows=rows,
            )
            row_count = result.row_count
    except Exception as e:  # noqa: BLE001
        dur = int((time.time() - t0) * 1000)
        _log.error(
            f"tool_error collection={collection} operation={operation} "
            f"error={e!r} duration_ms={dur}"
        )
        return format_error_result(purpose=purpose, error=f"查询执行出错：{e}")

    dur = int((time.time() - t0) * 1000)
    _log.info(
        f"tool_call_end collection={collection} operation={operation} "
        f"row_count={row_count} field_truncated={result.field_truncated} "
        f"tool_message_truncated={result.truncated} "
        f"estimated_tokens_before={result.estimated_tokens_before} "
        f"estimated_tokens_after={result.estimated_tokens} "
        f"truncation_reason={result.truncation_reason} duration_ms={dur} "
        f"preview_200={result.preview[:200]!r}"
    )
    return result
