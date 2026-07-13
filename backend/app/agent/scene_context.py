"""Build dynamic scene-count context for the agent system prompt.

The agent should know the rough original-outline scene range before its first
LLM call, but this probe must never block the chat path. On Mongo errors or
suspiciously small counts, return a conservative instruction that tells the
model to verify scene_sort from the original table before relying on the range.
"""
from __future__ import annotations

from app.config import settings
from app.db.mongo_client import get_db
from app.logging_config import get_logger

_log = get_logger("tool")

OUTLINE_COLLECTION = "seca_gen_scene_outline"
SUSPICIOUS_SCENE_COUNT_MAX = 3
MAX_SCENE_SCAN_ROWS = 20000


def _scene_sort_key(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _scan_scene_sorts(coll, filter_: dict) -> tuple[int, list[int]]:
    cursor = coll.find(
        filter_,
        {"_id": 0, "scene_sort": 1},
        limit=MAX_SCENE_SCAN_ROWS,
        max_time_ms=settings.mongo_max_time_ms,
    )
    sorts = sorted({
        n for row in cursor
        if (n := _scene_sort_key(row.get("scene_sort"))) is not None
    })
    return len(sorts), sorts


def build_scene_count_context(script_id: str) -> str:
    """Return one prompt paragraph describing original-table scene count."""
    if not script_id:
        return (
            "- 场次数未可靠确认：缺少 script_id。涉及全剧核实或“所有场次”时，"
            "必须先查询 seca_gen_scene_outline 的 scene_sort 范围。"
        )

    try:
        coll = get_db()[OUTLINE_COLLECTION]
        active_filter = {"script_id": script_id, "is_deleted": 0}
        active_docs = coll.count_documents(
            active_filter,
            maxTimeMS=settings.mongo_max_time_ms,
        )
        active_scene_count, active_sorts = _scan_scene_sorts(coll, active_filter)
    except Exception as e:  # noqa: BLE001
        _log.warning(f"scene_count_probe_error script_id={script_id} error={e!r}")
        return (
            "- 场次数未可靠确认：启动前查询原文表失败。涉及全剧核实、数量、名单、"
            "是否存在或“所有场次”时，必须先查询 seca_gen_scene_outline 的 scene_sort "
            "范围，再按原文表实时结果回答。"
        )

    if active_scene_count > SUSPICIOUS_SCENE_COUNT_MAX:
        start = active_sorts[0]
        end = active_sorts[-1]
        gap_note = ""
        if active_scene_count != end - start + 1:
            gap_note = "；scene_sort 存在缺号，以实际查到的 scene_sort 列表为准"
        return (
            f"- 原文表检测到可靠场次数：{active_scene_count} 场"
            f"（基于 {OUTLINE_COLLECTION}.scene_sort 去重，文档数 {active_docs}，"
            f"scene_sort 范围 {start}-{end}{gap_note}）。涉及全剧核实时，"
            "应覆盖这些原文场次；若后续查询发现数据变化，以原文表实时结果为准。"
        )

    # Compatibility mode: active rows are empty or suspiciously small. Probe all
    # rows with the same script_id once to distinguish "no active data" from a
    # likely is_deleted/status mismatch, but still keep the prompt conservative.
    try:
        all_filter = {"script_id": script_id}
        all_docs = coll.count_documents(
            all_filter,
            maxTimeMS=settings.mongo_max_time_ms,
        )
        all_scene_count, all_sorts = _scan_scene_sorts(coll, all_filter)
    except Exception as e:  # noqa: BLE001
        _log.warning(f"scene_count_probe_verify_error script_id={script_id} error={e!r}")
        all_docs = 0
        all_scene_count = 0
        all_sorts = []

    if all_scene_count > SUSPICIOUS_SCENE_COUNT_MAX:
        return (
            f"- 场次数疑似异常：按 is_deleted=0 只检测到 {active_scene_count} 场"
            f"（文档数 {active_docs}），但不加 is_deleted 条件可见 {all_scene_count} 场"
            f"（文档数 {all_docs}，scene_sort 范围 {all_sorts[0]}-{all_sorts[-1]}）。"
            "回答前必须用 seca_gen_scene_outline 核实当前有效 scene_sort 范围，"
            "不要直接依赖启动前场次数。"
        )

    return (
        f"- 场次数未可靠确认：原文表当前只检测到 {active_scene_count} 场"
        f"（有效文档数 {active_docs}；全量同 script_id 场次数 {all_scene_count}，"
        f"文档数 {all_docs}）。这可能是短剧、数据未入库或过滤条件异常。"
        "涉及全剧核实、数量、名单、是否存在或“所有场次”时，必须先查询 "
        "seca_gen_scene_outline 的 scene_sort 范围，并在回答中说明资料范围。"
    )
