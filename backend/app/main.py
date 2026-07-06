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
    _log.info(
        f"app_startup env={settings.app_env} provider={settings.llm_provider} model={settings.llm_model} "
        f"mongo_configured={bool(settings.mongo_uri)} "
        f"llm_configured={settings.llm_configured} "
        f"redis_configured={bool(settings.redis_url)} "
        f"history_mongo_configured={bool((settings.history_mongo_uri or settings.mongo_uri) and (settings.history_mongo_db or settings.mongo_db))}"
    )
