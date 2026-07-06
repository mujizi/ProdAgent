"""应用配置：从环境变量 / .env 读取，全局单例 settings。

所有阈值（轮数、预算、截断、token 系数）集中在此，避免散落在各模块导致口径不一致。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),  # 允许 model_max_input_tokens 等字段名
    )

    # 应用
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # DashScope Bailian OpenAI-compatible / LLM
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://llm-sun9d4d50ex0o5wu.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3.7-max"
    dashscope_enable_thinking: bool = False
    dashscope_max_tokens: int = 0

    # Azure fallback: used when DashScope/Qwen rejects input via provider risk control.
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_deployment: str = "gpt-5.5"
    azure_openai_max_completion_tokens: int = 16384
    azure_fallback_enabled: bool = True

    # Legacy OpenRouter settings are kept so old local .env files do not break settings loading.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-5.5"

    # Mongo
    mongo_uri: str = ""
    mongo_db: str = ""

    # Redis / History persistence
    redis_url: str = ""
    redis_socket_connect_timeout: int = 5
    redis_socket_timeout: int = 10
    redis_retry_attempts: int = 2
    history_ttl_seconds: int = 86400
    history_mongo_uri: str = ""
    history_mongo_db: str = ""
    history_session_collection: str = "agent_chat_sessions"
    history_message_collection: str = "agent_chat_messages"
    history_persist_mongo: bool = True
    history_redis_required: bool = False

    # Agent / 工具循环。max_tool_rounds<=0 表示不限轮数（由模型自行停止结束）
    max_tool_rounds: int = 0
    default_tool_limit: int = 20
    max_tool_rows: int = 50
    max_tool_chars: int = 16000
    max_tool_estimated_tokens: int = 8000
    max_regex_length: int = 50
    max_content_field_chars: int = 8000
    mongo_max_time_ms: int = 5000

    # 第一层：tool message 轻量剪枝。总 token 超阈值时只保留最近 N 个完整，其余占位串。
    keep_latest_tool_messages: int = 4
    tool_compact_token_threshold: int = 64000

    # 第二层：会话级 LLM 摘要压缩（OpenCode 风格：保留最近一部分 + 旧的折叠成摘要）。
    # model_max_input_tokens 当前写死 50 万；换模型时改这里即可。
    model_max_input_tokens: int = 500000
    compact_trigger_pct: float = 0.85          # 达 model_max_input_tokens × pct 触发
    compact_recent_protect_tokens: int = 8000  # 受保护的最近区(逐字保留)token 下限
    min_recent_turns: int = 3                  # 至少保留最近几个完整 turn
    summary_model: str = ""                    # 摘要用模型，空=用 dashscope_model

    @property
    def compact_trigger_tokens(self) -> int:
        return int(self.model_max_input_tokens * self.compact_trigger_pct)

    @property
    def llm_model(self) -> str:
        return self.dashscope_model

    @property
    def llm_provider(self) -> str:
        return "dashscope"

    @property
    def llm_configured(self) -> bool:
        return bool(
            self.dashscope_api_key
            and self.dashscope_base_url
            and self.dashscope_model
        )

    @property
    def azure_fallback_configured(self) -> bool:
        return bool(
            self.azure_fallback_enabled
            and self.azure_openai_api_key
            and self.azure_openai_endpoint
            and self.azure_openai_deployment
        )

    # token 粗估系数：中文用 2
    chars_per_token: int = 2

    # 日志
    log_level: str = "INFO"
    log_dir: str = "logs"

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def content_limit_max(self) -> int:
        """查询 content 字段时的 limit 上限（plan §9.1：查 content 时 limit 最大 10）。"""
        return 10


@lru_cache
def get_settings() -> "Settings":
    return Settings()


settings = get_settings()
