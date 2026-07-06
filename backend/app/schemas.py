"""API 请求/响应 Pydantic 模型。"""
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field("dev_user", description="用户 ID")
    session_id: str = Field(..., description="会话 ID")
    script_id: str = Field(..., description="剧本 ID")
    question: str = Field(..., description="用户问题")


class ChatResponse(BaseModel):
    user_id: str
    script_id: str
    session_id: str
    answer: str


class ToolDebugRequest(BaseModel):
    script_id: str
    args: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    app_env: str
    model: str
    mongo_configured: bool
    llm_configured: bool
    redis_configured: bool = False
    history_mongo_configured: bool = False
