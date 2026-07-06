"""Mongo 查询硬约束守卫（plan §8 / §9.1）。

纯逻辑、无 IO，可离线 pytest。职责：
- collection 白名单
- operation 白名单（find / count）
- 禁止危险 operator（$out/$merge/$where/$function/$accumulator 等）
- 规范化超长 regex（优先保留前若干个 | 分隔关键词）
- limit normalize（默认 20，最大 50；查 content 时最大 10）
- 强制注入 script_id
- projection 默认 {"_id": 0}
"""
from __future__ import annotations

from app.config import settings

ALLOWED_COLLECTIONS = {
    "seca_gen_scene_outline",    # 剧本原文表（contents 拼接）
    "seca_scene_analysis",       # 场景摘要表（scene_brief）
    "seca_element_type_detail",  # 元素表（人物/服装/化妆/道具/场景）
}

ALLOWED_OPERATIONS = {"find", "count"}

# 每表默认精简 projection（模型未指定 projection 时使用，去噪省 token）。
# outline 默认含 contents → 命中 content → limit 上限压到 10。
DEFAULT_PROJECTIONS = {
    "seca_gen_scene_outline": {
        "_id": 0, "scene_sort": 1, "scene_title": 1,
        "scene_summary": 1, "contents": 1,
    },
    "seca_scene_analysis": {
        "_id": 0, "scene_sort": 1, "scene_title": 1, "scene_brief": 1,
        "scene_location": 1, "interior_exterior": 1, "time_of_day": 1,
    },
    "seca_element_type_detail": {
        "_id": 0, "element_type_code": 1, "element_name": 1, "remark": 1,
    },
}

# 禁止出现在 filter / projection / sort 任意层级的 operator
FORBIDDEN_OPERATORS = {
    "$where",
    "$function",
    "$accumulator",
    "$out",
    "$merge",
    "$expr",  # 可携带 $function，保守禁用
}

# content 类字段：命中则把 limit 压到 content_limit_max(=10)。
# "content" 是 "contents" / "content_text" 的子串，统一覆盖原文字段。
CONTENT_FIELD_HINTS = {"content", "original", "text", "raw"}


class GuardError(ValueError):
    """守卫拒绝的查询。message 直接可作为工具错误返回给模型。"""


def _walk(obj):
    """递归遍历 dict/list，yield 每一个 (key, value)。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _check_forbidden_operators(obj) -> None:
    for k, _v in _walk(obj):
        if isinstance(k, str) and k in FORBIDDEN_OPERATORS:
            raise GuardError(f"禁止使用危险操作符: {k}")


def _check_regex_length(obj) -> None:
    max_len = settings.max_regex_length
    for k, v in _walk(obj):
        if isinstance(k, str) and k == "$regex" and isinstance(v, str):
            if len(v) > max_len:
                raise GuardError(
                    f"$regex 超长（{len(v)} > {max_len}），请用更短的关键词"
                )


def _shorten_regex(pattern: str, max_len: int) -> str:
    """把模型生成的超长 regex 缩成可执行的短关键词。

    常见形态是 "服装|衣服|外套|..."。优先按 | 保留尽可能多的完整关键词；
    如果没有可切分关键词，则保守截断到 max_len，避免工具调用直接失败。
    """
    if len(pattern) <= max_len:
        return pattern

    if "|" in pattern:
        parts = [p.strip() for p in pattern.split("|") if p.strip()]
        kept: list[str] = []
        for part in parts:
            candidate = "|".join([*kept, part])
            if len(candidate) <= max_len:
                kept.append(part)
            elif kept:
                break
            else:
                return part[:max_len]
        if kept:
            return "|".join(kept)

    return pattern[:max_len]


def _normalize_regex_lengths(obj):
    """递归复制对象，并把过长 $regex 字符串缩短到配置上限。"""
    max_len = settings.max_regex_length
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and k == "$regex" and isinstance(v, str):
                out[k] = _shorten_regex(v, max_len)
            else:
                out[k] = _normalize_regex_lengths(v)
        return out
    if isinstance(obj, list):
        return [_normalize_regex_lengths(item) for item in obj]
    return obj


def _projection_touches_content(projection: dict | None) -> bool:
    if not projection:
        # 无 projection（默认会返回所有字段）→ 可能带 content，保守视为 True
        return True
    # 忽略 _id（它常以 {"_id": 0} 出现，不代表查询意图）
    fields = {k: v for k, v in projection.items() if k != "_id"}
    if not fields:
        # 只有 _id 约束 → 等同返回所有其它字段 → 保守视为 True
        return True
    # 只要有任一被显式包含的字段命中 content 提示，即视为查 content
    for field, include in fields.items():
        if include in (1, True) and any(h in field.lower() for h in CONTENT_FIELD_HINTS):
            return True
    # 排除型 projection（非 _id 字段值为 0/False）→ 无法确定是否含 content → 保守 True
    if any(v in (0, False) for v in fields.values()):
        return True
    return False


def validate_and_normalize(script_id: str, args: dict) -> dict:
    """校验并规范化工具参数，返回可直接执行的安全 args。

    返回的 dict 含: collection / operation / filter / projection / sort / limit / purpose
    （filter 已强制注入 script_id；limit 已 normalize）。
    抛 GuardError 表示拒绝。
    """
    if not script_id:
        raise GuardError("缺少 script_id，无法执行查询")

    collection = args.get("collection")
    if collection not in ALLOWED_COLLECTIONS:
        raise GuardError(
            f"collection 不在白名单内: {collection!r}，"
            f"允许: {sorted(ALLOWED_COLLECTIONS)}"
        )

    operation = args.get("operation")
    if operation not in ALLOWED_OPERATIONS:
        raise GuardError(
            f"operation 不允许: {operation!r}，只支持 {sorted(ALLOWED_OPERATIONS)}"
        )

    filter_ = args.get("filter") or {}
    if not isinstance(filter_, dict):
        raise GuardError("filter 必须是对象")

    projection = args.get("projection")
    if projection is not None and not isinstance(projection, dict):
        raise GuardError("projection 必须是对象")

    sort = args.get("sort")
    if sort is not None and not isinstance(sort, dict):
        raise GuardError("sort 必须是对象")

    purpose = args.get("purpose")
    if not purpose:
        raise GuardError("缺少 purpose（本次查询目的）")

    # 危险 operator 检查（filter + projection + sort 都查）
    for part in (filter_, projection, sort):
        if part:
            _check_forbidden_operators(part)

    # 规范化超长 regex 后再做长度校验，避免模型生成长关键词串导致工具调用失败。
    filter_ = _normalize_regex_lengths(filter_)
    projection = _normalize_regex_lengths(projection) if projection else projection
    sort = _normalize_regex_lengths(sort) if sort else sort

    # regex 长度检查（正常情况下已被上一步规范化，这里保留为防线）
    for part in (filter_, projection, sort):
        if part:
            _check_regex_length(part)

    # 强制注入 script_id + is_deleted=0（覆盖模型可能传入的同名字段）
    safe_filter = dict(filter_)
    safe_filter["script_id"] = script_id
    safe_filter["is_deleted"] = 0

    # projection：模型指定则用其值（补 _id:0），否则用每表默认精简 projection
    if projection:
        safe_projection = dict(projection)
        safe_projection.setdefault("_id", 0)
    else:
        safe_projection = dict(DEFAULT_PROJECTIONS[collection])

    # limit normalize（基于“最终生效的 projection”判断是否查 content）
    raw_limit = args.get("limit")
    limit = settings.default_tool_limit if raw_limit is None else int(raw_limit)
    if limit < 1:
        limit = 1
    cap = settings.max_tool_rows
    if operation == "find" and _projection_touches_content(safe_projection):
        cap = min(cap, settings.content_limit_max)
    if limit > cap:
        limit = cap

    return {
        "collection": collection,
        "operation": operation,
        "filter": safe_filter,
        "projection": safe_projection,
        "sort": sort,
        "limit": limit,
        "purpose": purpose,
    }
