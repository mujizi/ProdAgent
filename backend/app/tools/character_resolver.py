"""Character name resolver.

Resolution policy:
- Element extraction provides a candidate roster for the model to judge.
- The backend only confirms exact names found in candidates or original text.
- For misspellings/aliases, return ranked candidates and ask the model to
  clarify with the user instead of hard-coding typo rules in Python.
- If the element roster is empty, fall back to exact original-text lookup.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
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
from app.tools.budget import estimate_tokens
from app.tools.formatter import (
    PREVIEW_MAX,
    FormattedResult,
    format_db_unavailable_result,
    format_error_result,
)
from app.utils.json_utils import dumps

_log = get_logger("tool")

OUTLINE_COLLECTION = "seca_gen_scene_outline"
ELEMENT_COLLECTION = "seca_element_type_detail"
CHARACTER_TYPES = {"main_cast", "supporting_cast", "background_actor"}
MAX_ELEMENT_CANDIDATES = 500
MAX_RETURNED_CANDIDATES = 30
MAX_ORIGINAL_HITS = 20
MIN_CLARIFICATION_SCORE = 0.001


@dataclass
class _OriginalHit:
    scene_sort: int | None
    scene_title: str
    matched_text: str
    match_method: str


def _preview(text: str) -> str:
    return text[:PREVIEW_MAX]


def _formatted_resolution(payload: dict) -> FormattedResult:
    body = dumps(payload, indent=2)
    full = (
        "人物名解析结果\n"
        f"raw_name: {payload.get('raw_name', '')}\n"
        f"matched: {str(payload.get('matched', False)).lower()}\n"
        f"canonical_name: {payload.get('canonical_name') or ''}\n"
        f"confidence: {payload.get('confidence', 0)}\n"
        f"resolution: {payload.get('resolution', '')}\n\n"
        f"{body}\n"
    )
    tokens = estimate_tokens(full)
    return FormattedResult(
        full_result=full,
        preview=_preview(full),
        row_count=len(payload.get("original_hits") or []),
        truncated=False,
        field_truncated=False,
        estimated_tokens=tokens,
        estimated_tokens_before=tokens,
        truncation_reason=None,
        payload=payload,
    )


def _join_contents(contents) -> str:
    if not isinstance(contents, list):
        return ""
    parts = []
    for item in contents:
        if isinstance(item, dict) and item.get("content"):
            parts.append(str(item["content"]))
    return "\n".join(parts)


def _clean_name(raw_name: str) -> str:
    return re.sub(r"\s+", "", str(raw_name or "").strip())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    score = SequenceMatcher(None, a, b).ratio()
    if len(a) == len(b) and len(a) >= 2:
        same = sum(1 for x, y in zip(a, b) if x == y)
        score = max(score, same / len(a))
    if len(a) >= 3 and len(b) >= 3 and a[0] == b[0] and a[-1] == b[-1]:
        score = max(score, 0.86)
    return round(score, 3)


def _exact_name_forms(name: str) -> list[str]:
    """只返回可安全视为精确写法的完整名和明确分隔组成部分。"""
    cleaned = _clean_name(name)
    if not cleaned:
        return []
    parts = re.split(r"[·.\-—_/（）()《》\s]+", cleaned)
    return sorted({cleaned, *[part for part in parts if part]}, key=len)


def _name_forms(name: str) -> list[str]:
    """返回候选排序使用的比较形式；启发式前缀不代表精确命中。"""
    forms = set(_exact_name_forms(name))
    cleaned = _clean_name(name)
    if cleaned and not re.search(r"[·.\-—_/（）()《》]", cleaned) and len(cleaned) >= 4:
        forms.add(cleaned[:2])
    return sorted(forms, key=len)


def _candidate_score(raw_name: str, candidate_name: str) -> tuple[float, str]:
    best_score = 0.0
    best_reason = ""
    for form in _name_forms(candidate_name):
        if raw_name == form:
            return 1.0, "候选名完全一致"
        if raw_name and (raw_name in form or form in raw_name):
            score = 0.94 if len(raw_name) >= 2 else 0.8
            if score > best_score:
                best_score = score
                best_reason = "候选名包含输入"
        score = _similarity(raw_name, form)
        if score > best_score:
            best_score = score
            best_reason = "候选名相近"
    return best_score, best_reason


def _resolution_label(status: str, matched: bool) -> str:
    if not matched:
        if status == "resolver_error":
            return "查询失败，未能确认"
        if status == "needs_clarification":
            return "需要用户确认候选人物"
        return "未在剧本原文中确认"
    if status == "candidate_exact":
        return "人物候选信息中确认"
    if status == "original_exact":
        return "原文中确认"
    return "已确认"


def _element_candidates(script_id: str, raw_name: str) -> list[dict]:
    coll = get_db()[ELEMENT_COLLECTION]
    cursor = coll.find(
        {
            "script_id": script_id,
            "is_deleted": 0,
            "element_type_code": {"$in": sorted(CHARACTER_TYPES)},
        },
        {"_id": 0, "element_name": 1, "element_type_code": 1, "remark": 1},
        limit=MAX_ELEMENT_CANDIDATES,
        max_time_ms=settings.mongo_max_time_ms,
    )

    dedup: dict[str, dict] = {}
    for row in cursor:
        name = _clean_name(row.get("element_name", ""))
        if not name:
            continue
        score, reason = _candidate_score(raw_name, name)
        dedup[name] = {
            "name": name,
            "score": score,
            "reason": reason,
            "remark": row.get("remark", ""),
        }
    return sorted(
        dedup.values(),
        key=lambda x: (x["score"], bool(x.get("remark"))),
        reverse=True,
    )[:MAX_RETURNED_CANDIDATES]


def _candidate_exact_match(raw_name: str, candidates: list[dict]) -> str | None:
    for candidate in candidates:
        if raw_name in _exact_name_forms(candidate["name"]):
            return candidate["name"]
    return None


def _has_plausible_candidate(candidates: list[dict]) -> bool:
    return bool(candidates and candidates[0].get("score", 0) >= MIN_CLARIFICATION_SCORE)


def _original_exact_hits(script_id: str, raw_name: str) -> tuple[str | None, list[_OriginalHit], str]:
    coll = get_db()[OUTLINE_COLLECTION]
    cursor = coll.find(
        {
            "script_id": script_id,
            "is_deleted": 0,
            "contents.content": {"$regex": re.escape(raw_name)},
        },
        {"_id": 0, "scene_sort": 1, "scene_title": 1, "contents": 1},
        limit=MAX_ORIGINAL_HITS,
        max_time_ms=settings.mongo_max_time_ms,
    ).sort("scene_sort", 1)

    hits = []
    for row in cursor:
        text = _join_contents(row.get("contents"))
        if raw_name not in text:
            continue
        hits.append(_OriginalHit(
            scene_sort=row.get("scene_sort"),
            scene_title=str(row.get("scene_title") or ""),
            matched_text=raw_name,
            match_method="原文出现",
        ))
    if hits:
        return raw_name, hits, "original_exact"
    return None, [], "not_found"


def resolve_character_name(script_id: str, args: dict) -> FormattedResult:
    """Resolve a character name into exact match or candidate list."""
    raw_name = _clean_name(args.get("raw_name", ""))
    purpose = args.get("purpose", "")
    t0 = time.time()
    if not raw_name:
        return _formatted_resolution({
            "raw_name": raw_name,
            "matched": False,
            "canonical_name": None,
            "confidence": 0,
            "status": "invalid_request",
            "resolution": "缺少人物名",
            "clarification_required": False,
            "purpose": purpose,
            "message": "缺少 raw_name，无法解析人物名。",
            "candidates": [],
            "original_hits": [],
        })

    try:
        candidates = _element_candidates(script_id, raw_name)
        exact_candidate = _candidate_exact_match(raw_name, candidates)
        if exact_candidate:
            canonical = exact_candidate
            hits: list[_OriginalHit] = []
            status = "candidate_exact"
        else:
            canonical, hits, status = _original_exact_hits(script_id, raw_name)
            if not canonical and _has_plausible_candidate(candidates):
                status = "needs_clarification"
    except (ConnectionFailure, ProtocolError, WaitQueueTimeoutError, ConfigurationError) as exc:
        _log.exception(
            f"character_resolver_error raw_name={raw_name!r} "
            f"error_code=db_unavailable error_type={exc.__class__.__name__}"
        )
        return format_db_unavailable_result(purpose=purpose)
    except ExecutionTimeout as exc:
        _log.exception(
            f"character_resolver_error raw_name={raw_name!r} "
            f"error_code=db_timeout error_type={exc.__class__.__name__}"
        )
        return format_db_unavailable_result(purpose=purpose, error_code="db_timeout")
    except PyMongoError as exc:
        error_id = "tool_" + uuid.uuid4().hex[:12]
        _log.exception(
            f"character_resolver_error raw_name={raw_name!r} error_id={error_id} "
            f"error_code=query_failed error_type={exc.__class__.__name__}"
        )
        return format_error_result(
            purpose=purpose,
            error=f"人物资料查询失败，当前无法完成核实。（错误编号：{error_id}）",
            error_code="query_failed",
            payload={"error_id": error_id},
        )
    except RuntimeError as exc:
        if "MONGO_" in str(exc):
            _log.exception(
                f"character_resolver_error raw_name={raw_name!r} "
                f"error_code=db_unavailable error_type={exc.__class__.__name__}"
            )
            return format_db_unavailable_result(purpose=purpose)
        error_id = "tool_" + uuid.uuid4().hex[:12]
        _log.exception(
            f"character_resolver_error raw_name={raw_name!r} error_id={error_id} "
            f"error_code=internal_error error_type={exc.__class__.__name__}"
        )
        return format_error_result(
            purpose=purpose,
            error=f"人物资料处理失败，当前无法完成核实。（错误编号：{error_id}）",
            error_code="internal_error",
            payload={"error_id": error_id},
        )
    except Exception as exc:  # noqa: BLE001
        error_id = "tool_" + uuid.uuid4().hex[:12]
        _log.exception(
            f"character_resolver_error raw_name={raw_name!r} error_id={error_id} "
            f"error_code=internal_error error_type={exc.__class__.__name__}"
        )
        return format_error_result(
            purpose=purpose,
            error=f"人物资料处理失败，当前无法完成核实。（错误编号：{error_id}）",
            error_code="internal_error",
            payload={"error_id": error_id},
        )

    matched = bool(canonical)
    confidence = 0.0
    if matched:
        confidence = 1.0 if canonical == raw_name else 0.95

    payload = {
        "raw_name": raw_name,
        "matched": matched,
        "canonical_name": canonical if matched else None,
        "confidence": confidence,
        "status": status,
        "resolution": _resolution_label(status, matched),
        "clarification_required": status == "needs_clarification",
        "purpose": purpose,
        "authority": (
            "人物候选信息"
            if status == "candidate_exact"
            else ("剧本原文" if status == "original_exact" else "未确认")
        ),
        "message": (
            "已确认该人物名。"
            if matched else
            (
                "未直接确认该输入对应的人物。请根据候选人物列表判断最可能的人物，并向用户澄清确认。"
                if status == "needs_clarification" else
                "人物候选信息为空，且剧本原文未确认该人物名；当前资料中未确认该人物。"
            )
        ),
        "candidates": candidates,
        "original_hits": [
            {
                "scene_sort": h.scene_sort,
                "scene_title": h.scene_title,
                "matched_text": h.matched_text,
                "match_method": h.match_method,
            }
            for h in hits[:10]
        ],
    }

    dur = int((time.time() - t0) * 1000)
    _log.info(
        f"character_resolver_done raw_name={raw_name!r} matched={matched} "
        f"canonical={canonical!r} status={status} candidates={len(candidates)} "
        f"original_hits={len(hits)} duration_ms={dur}"
    )
    return _formatted_resolution(payload)
