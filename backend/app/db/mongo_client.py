"""pymongo 同步客户端（plan §0：不用 motor，调用处包 run_in_threadpool）。"""
from __future__ import annotations

from pymongo import MongoClient

from app.config import settings
from app.logging_config import get_logger

_log = get_logger("tool")
_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        if not settings.mongo_uri:
            raise RuntimeError("MONGO_URI 未配置")
        _client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
        _log.info("mongo_client_init")
    return _client


def get_db():
    if not settings.mongo_db:
        raise RuntimeError("MONGO_DB 未配置")
    return get_client()[settings.mongo_db]


def ping() -> bool:
    """连通性检查。"""
    get_client().admin.command("ping")
    return True
