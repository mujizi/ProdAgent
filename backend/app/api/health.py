"""健康检查（plan §6.6）。"""
from fastapi import APIRouter

from app.config import settings
from app.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        model=settings.llm_model,
        mongo_configured=bool(settings.mongo_uri and settings.mongo_db),
        llm_configured=settings.llm_configured,
        redis_configured=bool(settings.redis_url),
        history_mongo_configured=bool(
            (settings.history_mongo_uri or settings.mongo_uri)
            and (settings.history_mongo_db or settings.mongo_db)
        ),
    )
