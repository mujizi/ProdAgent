"""Redis client for hot chat history."""
from __future__ import annotations

from redis import Redis

from app.config import settings
from app.logging_config import get_logger

_log = get_logger("history")
_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL 未配置")
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_timeout=settings.redis_socket_timeout,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        _log.info("redis_client_init")
    return _client


def reset_redis() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None


def ping() -> bool:
    get_redis().ping()
    return True
