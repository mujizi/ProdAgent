"""日志配置（plan §14）。

四个分文件 logger：app / llm / tool / history，各写自己的文件，并统一带
trace_id / session_id / script_id（通过 contextvar 注入）。

用 loguru：每个域用 bind(domain=...) 区分，filter 到不同文件。
另提供 conversation_events.jsonl 的独立写入函数（history store 调用）。
"""
import sys
from contextvars import ContextVar
from pathlib import Path

from loguru import logger

from app.config import settings

# 请求级上下文：在请求入口 set，贯穿所有日志
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
session_id_var: ContextVar[str] = ContextVar("session_id", default="-")
script_id_var: ContextVar[str] = ContextVar("script_id", default="-")

_configured = False


def _patch(record):
    """把 contextvar 注入到每条日志的 extra 里。"""
    record["extra"].setdefault("trace_id", trace_id_var.get())
    record["extra"].setdefault("session_id", session_id_var.get())
    record["extra"].setdefault("script_id", script_id_var.get())
    record["extra"].setdefault("domain", "app")


_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | "
    "trace={extra[trace_id]} sess={extra[session_id]} script={extra[script_id]} | "
    "{extra[domain]} | {message}"
)


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.configure(patcher=_patch)

    # 控制台
    logger.add(sys.stderr, level=settings.log_level, format=_FORMAT, enqueue=True)

    # 四个域各写自己的文件
    for domain in ("app", "llm", "tool", "history"):
        logger.add(
            log_dir / f"{domain}.log",
            level=settings.log_level,
            format=_FORMAT,
            filter=(lambda d: (lambda rec: rec["extra"].get("domain") == d))(domain),
            rotation="20 MB",
            retention=5,
            encoding="utf-8",
            enqueue=True,
        )

    _configured = True


def get_logger(domain: str):
    """获取某个域的 logger（domain ∈ app/llm/tool/history）。"""
    return logger.bind(domain=domain)


def bind_context(*, trace_id: str | None = None, session_id: str | None = None,
                 script_id: str | None = None) -> None:
    if trace_id is not None:
        trace_id_var.set(trace_id)
    if session_id is not None:
        session_id_var.set(session_id)
    if script_id is not None:
        script_id_var.set(script_id)
