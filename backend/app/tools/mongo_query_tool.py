"""execute_mongo_query：同步执行只读 Mongo 查询。

流程：Guard 校验+规范化 → pymongo find/count（maxTimeMS）→ Formatter。
纯同步，调用方用 run_in_threadpool 包裹，避免阻塞事件循环。
"""
from __future__ import annotations

import time
import uuid

from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    ExecutionTimeout,
    ProtocolError,
    PyMongoError,
    WaitQueueTimeoutError,
)

from app.config import settings
from app.db.mongo_client import get_db
from app.logging_config import get_logger
from app.tools.formatter import (
    FormattedResult,
    format_count_result,
    format_db_unavailable_result,
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
            content = item.get("content")
            if content:
                parts.append(str(content))
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
    """outline 的 content_text 是派生字段，发给 Mongo 时映射回 contents。"""
    if not projection or collection != OUTLINE_COLLECTION:
        return projection
    if "content_text" in projection:
        mapped = {k: v for k, v in projection.items() if k != "content_text"}
        mapped["contents"] = projection["content_text"]
        return mapped
    return projection


def _to_mongo_filter(collection: str, filter_: dict) -> dict:
    """outline 的 content_text 是派生字段，发给 Mongo 时映射回 contents.content。"""
    if collection != OUTLINE_COLLECTION:
        return filter_

    def convert(value):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                mapped_key = "contents.content" if key == "content_text" else key
                out[mapped_key] = convert(item)
            return out
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return convert(filter_)


def _requested_scene_range(filter_: dict) -> dict[str, int] | None:
    condition = filter_.get("scene_sort")
    if isinstance(condition, bool):
        return None
    if isinstance(condition, int):
        return {"start": condition, "end": condition}
    if not isinstance(condition, dict):
        return None
    start = condition.get("$gte")
    if start is None and isinstance(condition.get("$gt"), int):
        start = condition["$gt"] + 1
    end = condition.get("$lte")
    if end is None and isinstance(condition.get("$lt"), int):
        end = condition["$lt"] - 1
    result = {}
    if isinstance(start, int) and not isinstance(start, bool):
        result["start"] = start
    if isinstance(end, int) and not isinstance(end, bool):
        result["end"] = end
    return result or None


def _next_scene_filter(filter_: dict, after_scene_sort: int) -> dict:
    """保留原范围上界，并把下界推进到指定场次之后。"""
    next_filter = {
        key: value for key, value in filter_.items()
        if key not in {"scene_sort"}
    }
    condition = filter_.get("scene_sort")
    next_condition: dict = {"$gt": after_scene_sort}
    if isinstance(condition, dict):
        if "$lt" in condition:
            next_condition["$lt"] = condition["$lt"]
        if "$lte" in condition:
            next_condition["$lte"] = condition["$lte"]
    next_filter["scene_sort"] = next_condition
    return next_filter


def _fetch_outline_page(coll, safe: dict) -> tuple[list[dict], bool, int | None]:
    """按完整 scene_sort 分页；limit 表示场次数而不是 Mongo 文档数。"""
    projection = _to_mongo_projection(OUTLINE_COLLECTION, safe["projection"])
    scene_cursor = coll.find(
        _to_mongo_filter(OUTLINE_COLLECTION, safe["filter"]),
        {"_id": 0, "scene_sort": 1},
        limit=0,
        max_time_ms=settings.mongo_max_time_ms,
    ).sort([("scene_sort", 1), ("_id", 1)])
    scene_sorts: list[int] = []
    for row in scene_cursor:
        scene_sort = row.get("scene_sort") if isinstance(row, dict) else None
        if isinstance(scene_sort, int) and not isinstance(scene_sort, bool):
            if not scene_sorts or scene_sorts[-1] != scene_sort:
                scene_sorts.append(scene_sort)
        if len(scene_sorts) > safe["limit"]:
            break

    selected_sorts = scene_sorts[:safe["limit"]]
    db_has_more = len(scene_sorts) > safe["limit"]
    db_next_scene_sort = scene_sorts[safe["limit"]] if db_has_more else None
    if not selected_sorts:
        return [], False, None

    page_filter = dict(safe["filter"])
    page_filter["scene_sort"] = {"$in": selected_sorts}
    rows = list(coll.find(
        _to_mongo_filter(OUTLINE_COLLECTION, page_filter),
        projection,
        max_time_ms=settings.mongo_max_time_ms,
    ).sort([("scene_sort", 1), ("_id", 1)]))
    return rows, db_has_more, db_next_scene_sort


def _safe_tool_error(purpose: str, error_code: str, message: str, exc: Exception) -> FormattedResult:
    error_id = "tool_" + uuid.uuid4().hex[:12]
    _log.exception(
        f"tool_error error_id={error_id} error_code={error_code} "
        f"error_type={exc.__class__.__name__}"
    )
    return format_error_result(
        purpose=purpose,
        error=f"{message}（错误编号：{error_id}）",
        error_code=error_code,
        payload={"error_id": error_id, "message": message},
    )


def execute_mongo_query(script_id: str, args: dict) -> FormattedResult:
    purpose = args.get("purpose", "")
    t0 = time.time()

    try:
        safe = validate_and_normalize(script_id, args)
    except GuardError as exc:
        _log.warning(
            f"tool_guard_reject purpose={purpose!r} reason={exc} "
            f"collection={args.get('collection')!r} operation={args.get('operation')!r}"
        )
        return format_error_result(
            purpose=purpose,
            error=f"查询被拒绝：{exc}",
            error_code="guard_rejected",
            payload={"message": str(exc)},
        )

    collection = safe["collection"]
    operation = safe["operation"]
    limit_requested = args.get("limit")
    _log.info(
        f"tool_call_start collection={collection} operation={operation} "
        f"purpose={purpose!r} limit_requested={limit_requested} limit_final={safe['limit']}"
    )

    try:
        coll = get_db()[collection]
        if operation == "count":
            count = coll.count_documents(
                safe["filter"], maxTimeMS=settings.mongo_max_time_ms
            )
            result = format_count_result(
                collection=collection,
                operation=operation,
                purpose=purpose,
                count=count,
            )
        else:
            if collection == OUTLINE_COLLECTION:
                rows, db_has_more, db_next_scene_sort = _fetch_outline_page(coll, safe)
                rows = _postprocess_outline_rows(rows)
            else:
                cursor = coll.find(
                    _to_mongo_filter(collection, safe["filter"]),
                    _to_mongo_projection(collection, safe["projection"]),
                    limit=safe["limit"],
                    max_time_ms=settings.mongo_max_time_ms,
                )
                if safe.get("sort"):
                    cursor = cursor.sort(list(safe["sort"].items()))
                rows = list(cursor)
                db_has_more = False
                db_next_scene_sort = None
            result = format_find_result(
                collection=collection,
                operation=operation,
                purpose=purpose,
                rows=rows,
                requested_range=_requested_scene_range(safe["filter"]),
                db_has_more=db_has_more,
                db_next_scene_sort=db_next_scene_sort,
            )
    except (ConnectionFailure, ProtocolError, WaitQueueTimeoutError, ConfigurationError) as exc:
        result = _safe_tool_error(
            purpose, "db_unavailable", "剧本数据库暂时连接不上，可以稍后再试。", exc
        )
    except ExecutionTimeout as exc:
        result = _safe_tool_error(
            purpose, "db_timeout", "剧本资料查询超时，可以稍后再试。", exc
        )
    except PyMongoError as exc:
        result = _safe_tool_error(
            purpose, "query_failed", "剧本资料查询失败，当前无法完成核实。", exc
        )
    except RuntimeError as exc:
        if "MONGO_" in str(exc):
            result = _safe_tool_error(
                purpose, "db_unavailable", "剧本数据库暂时连接不上，可以稍后再试。", exc
            )
        else:
            result = _safe_tool_error(
                purpose, "internal_error", "剧本资料处理失败，当前无法完成核实。", exc
            )
    except Exception as exc:  # noqa: BLE001
        result = _safe_tool_error(
            purpose, "internal_error", "剧本资料处理失败，当前无法完成核实。", exc
        )

    dur = int((time.time() - t0) * 1000)
    _log.info(
        f"tool_call_end collection={collection} operation={operation} "
        f"row_count={result.row_count} error_code={result.error_code} "
        f"field_truncated={result.field_truncated} "
        f"tool_message_truncated={result.truncated} "
        f"estimated_tokens_before={result.estimated_tokens_before} "
        f"estimated_tokens_after={result.estimated_tokens} "
        f"truncation_reason={result.truncation_reason} duration_ms={dur} "
        f"preview_200={result.preview[:200]!r}"
    )
    return result
