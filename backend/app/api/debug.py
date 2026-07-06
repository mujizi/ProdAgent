"""调试接口（plan §6.3 / §6.4 / §6.5）。"""
from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.history.local_history_store import clear_history, get_history, get_summary
from app.history.session_ref import session_ref_from_parts
from app.logging_config import get_logger
from app.schemas import ToolDebugRequest
from app.tools.mongo_query_tool import execute_mongo_query

router = APIRouter(prefix="/api/debug")
_log = get_logger("app")


@router.post("/tool")
async def debug_tool(req: ToolDebugRequest):
    """直接执行一次工具查询，便于联调 Mongo 与截断。"""
    result = await run_in_threadpool(execute_mongo_query, req.script_id, req.args)
    return {
        "preview": result.preview,
        "full_result": result.full_result,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "field_truncated": result.field_truncated,
        "estimated_tokens": result.estimated_tokens,
        "estimated_tokens_before": result.estimated_tokens_before,
        "truncation_reason": result.truncation_reason,
    }


@router.get("/history/{session_id}")
async def debug_history(session_id: str, user_id: str = "dev_user", script_id: str = "-"):
    key = session_ref_from_parts(user_id, script_id, session_id).session_key
    return {
        "user_id": user_id,
        "script_id": script_id,
        "session_id": session_id,
        "session_key": key,
        "summary": get_summary(key),
        "messages": get_history(key),
    }


@router.post("/history/{session_id}/clear")
async def debug_history_clear(session_id: str, user_id: str = "dev_user", script_id: str = "-"):
    key = session_ref_from_parts(user_id, script_id, session_id).session_key
    clear_history(key)
    return {"user_id": user_id, "script_id": script_id, "session_id": session_id, "cleared": True}
