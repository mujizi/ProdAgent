"""FastAPI 应用入口。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, debug, health
from app.config import settings
from app.db import redis_client
from app.history.local_history_store import ensure_history_indexes
from app.logging_config import get_logger, setup_logging

setup_logging()
_log = get_logger("app")

app = FastAPI(title="ProdAgent 剧本问答 MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(debug.router)


@app.on_event("startup")
async def _startup():
    if settings.history_redis_required:
        redis_client.ping()
    if settings.history_persist_mongo:
        ensure_history_indexes()
    history_mongo_configured = bool(
        (settings.history_mongo_uri or settings.mongo_uri)
        and (settings.history_mongo_db or settings.mongo_db)
    )
    _log.info(
        f"app_startup env={settings.app_env} "
        f"llm_provider={settings.llm_provider} llm_model={settings.llm_model} "
        f"summary_model={settings.summary_model or settings.llm_model} "
        f"llm_configured={settings.llm_configured} "
        f"azure_fallback_enabled={settings.azure_fallback_enabled} "
        f"azure_fallback_configured={settings.azure_fallback_configured} "
        f"mongo_configured={bool(settings.mongo_uri and settings.mongo_db)} "
        f"history_store={'redis' if settings.redis_url else 'memory'} "
        f"history_redis_required={settings.history_redis_required} "
        f"history_persist_mongo={settings.history_persist_mongo} "
        f"history_mongo_configured={history_mongo_configured} "
        f"cors_origins={settings.cors_origin_list!r} "
        f"max_tool_rounds={settings.max_tool_rounds} "
        f"max_tool_chars={settings.max_tool_chars} "
        f"max_tool_estimated_tokens={settings.max_tool_estimated_tokens} "
        f"max_content_field_chars={settings.max_content_field_chars} "
        f"content_query_limit_max={settings.content_query_limit_max} "
        f"model_max_input_tokens={settings.model_max_input_tokens} "
        f"chars_per_token={settings.chars_per_token}"
    )
