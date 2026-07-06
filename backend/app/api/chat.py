"""聊天接口（plan §6.1 / §6.2）。"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.loop import run_chat_stream
from app.history.local_history_store import acquire_session_lock, release_session_lock
from app.history.session_ref import session_ref_from_parts
from app.logging_config import get_logger
from app.schemas import ChatRequest, ChatResponse
from app.utils.ids import new_trace_id

router = APIRouter(prefix="/api/chat")
_log = get_logger("app")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 禁止 nginx/反代缓冲流
}


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    trace_id = new_trace_id()
    try:
        ref = session_ref_from_parts(req.user_id, req.script_id, req.session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    _log.info(f"request_start path=/api/chat/stream user={req.user_id} session={req.session_id}")
    if not acquire_session_lock(ref.session_key, trace_id):
        raise HTTPException(status_code=409, detail="同一会话正在处理中，请稍后再试")

    async def gen():
        try:
            async for event in run_chat_stream(
                user_id=req.user_id,
                session_id=req.session_id,
                script_id=req.script_id,
                question=req.question,
                trace_id=trace_id,
                history_key=ref.session_key,
            ):
                yield event
        finally:
            release_session_lock(ref.session_key, trace_id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """非流式：内部消费流式生成器，收集终答文本。"""
    import json

    trace_id = new_trace_id()
    try:
        ref = session_ref_from_parts(req.user_id, req.script_id, req.session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    _log.info(f"request_start path=/api/chat user={req.user_id} session={req.session_id}")
    if not acquire_session_lock(ref.session_key, trace_id):
        raise HTTPException(status_code=409, detail="同一会话正在处理中，请稍后再试")
    answer_parts: list[str] = []
    try:
        async for event in run_chat_stream(
            user_id=req.user_id,
            session_id=req.session_id,
            script_id=req.script_id,
            question=req.question,
            trace_id=trace_id,
            history_key=ref.session_key,
        ):
            # 解析 delta 事件累加文本
            lines = event.strip().split("\n")
            if lines and lines[0] == "event: delta":
                data = json.loads(lines[1][len("data: "):])
                answer_parts.append(data.get("text", ""))
    finally:
        release_session_lock(ref.session_key, trace_id)
    return ChatResponse(
        user_id=req.user_id,
        script_id=req.script_id,
        session_id=req.session_id,
        answer="".join(answer_parts),
    )
