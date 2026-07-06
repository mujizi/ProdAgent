"""Chat history store.

Production path:
- Redis DB keeps the hot active context for 24h TTL.
- MongoDB stores long-term session metadata and full message events asynchronously.

Offline fallback:
- If REDIS_URL is not configured (or Redis is unavailable and not required), use in-memory
  dictionaries so unit tests and local development can still run.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import threading
from pathlib import Path

from pymongo import MongoClient

from app.config import settings
from app.db.redis_client import get_redis, reset_redis
from app.history.session_ref import split_session_key
from app.logging_config import get_logger
from app.utils.json_utils import dumps, loads

_log = get_logger("history")

SESSION_HISTORY: dict[str, list[dict]] = {}
SESSION_SUMMARY: dict[str, str] = {}
SESSION_SEQ: dict[str, int] = {}
_lock = threading.Lock()
_mongo_client: MongoClient | None = None
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="history-mongo")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _history_key(session_key: str) -> str:
    return f"agent:history:{session_key}"


def _summary_key(session_key: str) -> str:
    return f"agent:summary:{session_key}"


def _seq_key(session_key: str) -> str:
    return f"agent:seq:{session_key}"


def lock_key(session_key: str) -> str:
    return f"agent:lock:{session_key}"


def acquire_session_lock(session_key: str, trace_id: str, ttl_seconds: int = 120) -> bool:
    if not _redis_available():
        return True
    try:
        return bool(_redis_call(lambda r: r.set(lock_key(session_key), trace_id, nx=True, ex=ttl_seconds)))
    except Exception as e:  # noqa: BLE001
        _log.error(f"session_lock_acquire_error error={e!r}")
        if settings.history_redis_required:
            raise
        return True


def release_session_lock(session_key: str, trace_id: str) -> None:
    if not _redis_available():
        return
    try:
        key = lock_key(session_key)
        def _release(r):
            if r.get(key) == trace_id:
                r.delete(key)
        _redis_call(_release)
    except Exception as e:  # noqa: BLE001
        _log.error(f"session_lock_release_error error={e!r}")
        if settings.history_redis_required:
            raise


def _jsonl_path() -> Path:
    p = Path(settings.log_dir) / "conversation_events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _write_event(*, trace_id: str, session_key: str, script_id: str, message: dict) -> None:
    ref = split_session_key(session_key)
    line = dumps({
        "trace_id": trace_id,
        "user_id": ref.user_id,
        "session_id": ref.session_id,
        "session_key": session_key,
        "script_id": script_id,
        "role": message.get("role"),
        "message": message,
    })
    with _jsonl_path().open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    _log.info(f"conversation_event_write role={message.get('role')}")


def _redis_available() -> bool:
    return bool(settings.redis_url)


def _redis_call(fn):
    attempts = max(1, settings.redis_retry_attempts)
    last_error: Exception | None = None
    for idx in range(attempts):
        try:
            return fn(get_redis())
        except Exception as e:  # noqa: BLE001
            last_error = e
            _log.warning(f"redis_call_retry attempt={idx + 1}/{attempts} error={e!r}")
            reset_redis()
    assert last_error is not None
    raise last_error


def _redis_get_json(key: str):
    raw = _redis_call(lambda r: r.get(key))
    if not raw:
        return None
    return loads(raw)


def _redis_set_json(key: str, value) -> None:
    _redis_call(lambda r: r.setex(key, settings.history_ttl_seconds, dumps(value)))


def _redis_delete(*keys: str) -> None:
    if keys:
        _redis_call(lambda r: r.delete(*keys))


def _get_mongo_db():
    global _mongo_client
    uri = settings.history_mongo_uri or settings.mongo_uri
    db_name = settings.history_mongo_db or settings.mongo_db
    if not uri or not db_name:
        raise RuntimeError("history mongo 未配置")
    if _mongo_client is None:
        _mongo_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _log.info("history_mongo_client_init")
    return _mongo_client[db_name]


def ensure_history_indexes() -> None:
    if not settings.history_persist_mongo:
        return
    try:
        db = _get_mongo_db()
        db[settings.history_session_collection].create_index(
            [("session_key", 1)], unique=True, name="uniq_session_key"
        )
        db[settings.history_session_collection].create_index(
            [("user_id", 1), ("script_id", 1), ("updated_at", -1)],
            name="user_script_updated",
        )
        db[settings.history_message_collection].create_index(
            [("session_key", 1), ("seq", 1)], name="session_seq"
        )
        db[settings.history_message_collection].create_index(
            [("trace_id", 1)], name="trace_id"
        )
        _log.info("history_mongo_indexes_ready")
    except Exception as e:  # noqa: BLE001
        _log.error(f"history_mongo_index_error error={e!r}")
        raise


def _persist_message_to_mongo(
    *, session_key: str, message: dict, trace_id: str, script_id: str, seq: int
) -> None:
    if not settings.history_persist_mongo:
        return
    ref = split_session_key(session_key)
    db = _get_mongo_db()
    now = _utcnow()
    db[settings.history_message_collection].insert_one({
        "session_key": session_key,
        "user_id": ref.user_id,
        "script_id": script_id,
        "session_id": ref.session_id,
        "trace_id": trace_id,
        "seq": seq,
        "role": message.get("role"),
        "message": message,
        "created_at": now,
    })
    db[settings.history_session_collection].update_one(
        {"session_key": session_key},
        {
            "$set": {
                "user_id": ref.user_id,
                "script_id": script_id,
                "session_id": ref.session_id,
                "updated_at": now,
                "last_message_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
                "status": "active",
            },
            "$inc": {"message_count": 1},
        },
        upsert=True,
    )


def _persist_summary_to_mongo(session_key: str, summary: str) -> None:
    if not settings.history_persist_mongo:
        return
    ref = split_session_key(session_key)
    db = _get_mongo_db()
    now = _utcnow()
    db[settings.history_session_collection].update_one(
        {"session_key": session_key},
        {
            "$set": {
                "user_id": ref.user_id,
                "script_id": ref.script_id,
                "session_id": ref.session_id,
                "summary": summary,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now, "status": "active"},
        },
        upsert=True,
    )


def _submit_mongo(fn, **kwargs) -> None:
    if not settings.history_persist_mongo:
        return

    def _run():
        try:
            fn(**kwargs)
        except Exception as e:  # noqa: BLE001
            _log.error(f"history_mongo_persist_error error={e!r}")

    _executor.submit(_run)


def _load_from_mongo(session_key: str) -> list[dict]:
    if not settings.history_persist_mongo:
        return []
    try:
        db = _get_mongo_db()
        cursor = db[settings.history_message_collection].find(
            {"session_key": session_key}, {"_id": 0, "message": 1}
        ).sort("seq", 1)
        messages = [row["message"] for row in cursor if "message" in row]
        if messages:
            _log.info(f"history_mongo_restore message_count={len(messages)}")
        return messages
    except Exception as e:  # noqa: BLE001
        _log.error(f"history_mongo_restore_error error={e!r}")
        return []


def _load_summary_from_mongo(session_key: str) -> str | None:
    if not settings.history_persist_mongo:
        return None
    try:
        db = _get_mongo_db()
        row = db[settings.history_session_collection].find_one(
            {"session_key": session_key}, {"_id": 0, "summary": 1}
        )
        summary = row.get("summary") if row else None
        if summary:
            _log.info(f"summary_mongo_restore summary_len={len(summary)}")
        return summary
    except Exception as e:  # noqa: BLE001
        _log.error(f"summary_mongo_restore_error error={e!r}")
        return None


def get_history(session_id: str) -> list[dict]:
    session_key = session_id
    if _redis_available():
        try:
            hist = _redis_get_json(_history_key(session_key))
            if hist is None:
                hist = _load_from_mongo(session_key)
                if hist:
                    _redis_set_json(_history_key(session_key), hist)
                    _redis_call(lambda r: r.setex(_seq_key(session_key), settings.history_ttl_seconds, len(hist)))
            hist = hist or []
            _log.info(f"history_load source=redis message_count={len(hist)}")
            return [dict(m) for m in hist]
        except Exception as e:  # noqa: BLE001
            _log.error(f"history_redis_load_error error={e!r}")
            if settings.history_redis_required:
                raise

    with _lock:
        hist = SESSION_HISTORY.get(session_key, [])
        _log.info(f"history_load source=memory message_count={len(hist)}")
        return [dict(m) for m in hist]


def append_message(
    session_id: str,
    message: dict,
    *,
    trace_id: str = "-",
    script_id: str = "-",
    persist: bool = True,
) -> None:
    session_key = session_id
    seq = 0
    if _redis_available():
        try:
            hist = _redis_get_json(_history_key(session_key)) or []
            before = len(hist)
            hist.append(message)
            after = len(hist)
            seq = int(_redis_call(lambda r: r.incr(_seq_key(session_key))))
            if seq == 1 and before > 0:
                seq = before + 1
                _redis_call(lambda r: r.set(_seq_key(session_key), seq))
            _redis_call(lambda r: r.expire(_seq_key(session_key), settings.history_ttl_seconds))
            _redis_set_json(_history_key(session_key), hist)
            _log.info(f"history_append source=redis role={message.get('role')} "
                      f"message_count_before={before} message_count_after={after}")
        except Exception as e:  # noqa: BLE001
            _log.error(f"history_redis_append_error error={e!r}")
            if settings.history_redis_required:
                raise
            with _lock:
                before = len(SESSION_HISTORY.get(session_key, []))
                SESSION_HISTORY.setdefault(session_key, []).append(message)
                after = before + 1
                SESSION_SEQ[session_key] = after
                seq = after
            _log.info(f"history_append source=memory role={message.get('role')} "
                      f"message_count_before={before} message_count_after={after}")
    else:
        with _lock:
            before = len(SESSION_HISTORY.get(session_key, []))
            SESSION_HISTORY.setdefault(session_key, []).append(message)
            after = before + 1
            SESSION_SEQ[session_key] = after
            seq = after
        _log.info(f"history_append source=memory role={message.get('role')} "
                  f"message_count_before={before} message_count_after={after}")

    if persist:
        _write_event(
            trace_id=trace_id, session_key=session_key,
            script_id=script_id, message=message,
        )
        _submit_mongo(
            _persist_message_to_mongo,
            session_key=session_key,
            message=message,
            trace_id=trace_id,
            script_id=script_id,
            seq=seq,
        )


def replace_history(session_id: str, messages: list[dict]) -> None:
    session_key = session_id
    if _redis_available():
        try:
            before = len(_redis_get_json(_history_key(session_key)) or [])
            _redis_set_json(_history_key(session_key), [dict(m) for m in messages])
            _log.info(f"history_replace source=redis message_count_before={before} "
                      f"message_count_after={len(messages)}")
            return
        except Exception as e:  # noqa: BLE001
            _log.error(f"history_redis_replace_error error={e!r}")
            if settings.history_redis_required:
                raise

    with _lock:
        before = len(SESSION_HISTORY.get(session_key, []))
        SESSION_HISTORY[session_key] = [dict(m) for m in messages]
        after = len(messages)
    _log.info(f"history_replace source=memory message_count_before={before} "
              f"message_count_after={after}")


def clear_history(session_id: str) -> None:
    session_key = session_id
    if _redis_available():
        try:
            before = len(_redis_get_json(_history_key(session_key)) or [])
            _redis_delete(_history_key(session_key), _summary_key(session_key), _seq_key(session_key))
            _log.info(f"history_clear source=redis message_count_before={before} message_count_after=0")
            return
        except Exception as e:  # noqa: BLE001
            _log.error(f"history_redis_clear_error error={e!r}")
            if settings.history_redis_required:
                raise
    with _lock:
        before = len(SESSION_HISTORY.get(session_key, []))
        SESSION_HISTORY.pop(session_key, None)
        SESSION_SUMMARY.pop(session_key, None)
        SESSION_SEQ.pop(session_key, None)
    _log.info(f"history_clear source=memory message_count_before={before} message_count_after=0")


def get_summary(session_id: str) -> str | None:
    session_key = session_id
    if _redis_available():
        try:
            summary = _redis_call(lambda r: r.get(_summary_key(session_key)))
            if summary is not None:
                _redis_call(lambda r: r.expire(_summary_key(session_key), settings.history_ttl_seconds))
            else:
                summary = _load_summary_from_mongo(session_key)
                if summary:
                    _redis_call(lambda r: r.setex(_summary_key(session_key), settings.history_ttl_seconds, summary))
            return summary
        except Exception as e:  # noqa: BLE001
            _log.error(f"summary_redis_get_error error={e!r}")
            if settings.history_redis_required:
                raise
    with _lock:
        return SESSION_SUMMARY.get(session_key)


def set_summary(session_id: str, summary: str) -> None:
    session_key = session_id
    if _redis_available():
        try:
            _redis_call(lambda r: r.setex(_summary_key(session_key), settings.history_ttl_seconds, summary))
            _log.info(f"summary_set source=redis summary_len={len(summary)}")
            _submit_mongo(_persist_summary_to_mongo, session_key=session_key, summary=summary)
            return
        except Exception as e:  # noqa: BLE001
            _log.error(f"summary_redis_set_error error={e!r}")
            if settings.history_redis_required:
                raise
    with _lock:
        SESSION_SUMMARY[session_key] = summary
    _log.info(f"summary_set source=memory summary_len={len(summary)}")
    _submit_mongo(_persist_summary_to_mongo, session_key=session_key, summary=summary)
