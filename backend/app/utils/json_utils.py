"""JSON 序列化工具：统一处理中文与 Mongo 特殊类型。"""
import datetime
import json
from typing import Any

try:  # pymongo 存在时支持 ObjectId
    from bson import ObjectId
except Exception:  # pragma: no cover - 纯逻辑测试环境可能无 bson
    ObjectId = None  # type: ignore


def _default(o: Any) -> Any:
    if ObjectId is not None and isinstance(o, ObjectId):
        return str(o)
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    return str(o)


def dumps(obj: Any, *, indent: int | None = None) -> str:
    """中文不转义（ensure_ascii=False），便于日志与工具结果可读。"""
    return json.dumps(obj, ensure_ascii=False, default=_default, indent=indent)


def loads(text: str) -> Any:
    return json.loads(text)
