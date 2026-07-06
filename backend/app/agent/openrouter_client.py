"""DashScope OpenAI-compatible LLM 客户端（保留文件名以兼容现有导入路径）。

用 AsyncOpenAI 调阿里云百炼兼容模式。两类调用：
- complete_with_tools: 工具轮，stream=False，带 tools
- stream_final_answer: 终答，stream=True，逐 token yield

全部走 llm.log。
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.config import settings
from app.logging_config import get_logger

_log = get_logger("llm")
_client: AsyncOpenAI | None = None
_azure_client: AsyncAzureOpenAI | None = None

# 最近一次 complete_with_tools 的真实 prompt_tokens（供压缩触发用更准的口径）。
# mock 测试不会更新它 → 保持 None → 调用方回退到估算。
LAST_PROMPT_TOKENS: int | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.llm_configured:
            raise RuntimeError("DashScope 未配置，请检查 DASHSCOPE_API_KEY / DASHSCOPE_BASE_URL / DASHSCOPE_MODEL")
        _client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
    return _client


def get_azure_client() -> AsyncAzureOpenAI:
    global _azure_client
    if _azure_client is None:
        if not settings.azure_fallback_configured:
            raise RuntimeError("Azure fallback 未配置，请检查 AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_DEPLOYMENT")
        _azure_client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
    return _azure_client


def _common_kwargs() -> dict:
    kwargs = {
        "extra_body": {"enable_thinking": settings.dashscope_enable_thinking},
    }
    if settings.dashscope_max_tokens > 0:
        kwargs["max_tokens"] = settings.dashscope_max_tokens
    return kwargs


def _is_provider_risk_error(error: Exception) -> bool:
    text = repr(error)
    return (
        "data_inspection_failed" in text
        or "Input text data may contain inappropriate content" in text
    )


def _azure_kwargs() -> dict:
    return {"max_completion_tokens": settings.azure_openai_max_completion_tokens}


async def complete_with_tools(messages: list[dict], tools: list[dict]) -> Any:
    """工具轮：非流式，返回 message 对象（可能含 tool_calls）。"""
    client = get_client()
    t0 = time.time()
    _log.info(
        f"llm_call_start provider={settings.llm_provider} model={settings.llm_model} stream=false "
        f"message_count={len(messages)} tool_enabled=true"
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
            **_common_kwargs(),
        )
    except Exception as e:  # noqa: BLE001
        _log.error(f"llm_error stage=tools error={e!r}")
        if not (_is_provider_risk_error(e) and settings.azure_fallback_configured):
            raise
        _log.warning(
            f"llm_fallback_start from_provider=dashscope to_provider=azure "
            f"reason=data_inspection_failed model={settings.azure_openai_deployment} stage=tools"
        )
        resp = await get_azure_client().chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
            **_azure_kwargs(),
        )
    msg = resp.choices[0].message
    tool_calls = msg.tool_calls or []
    global LAST_PROMPT_TOKENS
    if resp.usage is not None:
        LAST_PROMPT_TOKENS = resp.usage.prompt_tokens
    dur = int((time.time() - t0) * 1000)
    _log.info(
        f"llm_call_end stream=false has_tool_calls={bool(tool_calls)} "
        f"tool_call_count={len(tool_calls)} duration_ms={dur}"
    )
    if tool_calls:
        for tc in tool_calls:
            _log.info(f"tool_call_detected name={tc.function.name}")
    return msg


async def complete_text(messages: list[dict], model: str | None = None) -> str:
    """通用非流式纯文本补全（无工具）。用于会话摘要压缩。"""
    client = get_client()
    use_model = model or settings.llm_model
    t0 = time.time()
    _log.info(f"llm_call_start provider={settings.llm_provider} model={use_model} stream=false purpose=summary "
              f"message_count={len(messages)} tool_enabled=false")
    try:
        resp = await client.chat.completions.create(
            model=use_model,
            messages=messages,
            stream=False,
            **_common_kwargs(),
        )
    except Exception as e:  # noqa: BLE001
        _log.error(f"llm_error stage=summary error={e!r}")
        if not (_is_provider_risk_error(e) and settings.azure_fallback_configured):
            raise
        _log.warning(
            f"llm_fallback_start from_provider=dashscope to_provider=azure "
            f"reason=data_inspection_failed model={settings.azure_openai_deployment} stage=summary"
        )
        resp = await get_azure_client().chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages,
            stream=False,
            **_azure_kwargs(),
        )
    text = resp.choices[0].message.content or ""
    dur = int((time.time() - t0) * 1000)
    _log.info(f"llm_call_end stream=false purpose=summary text_len={len(text)} duration_ms={dur}")
    return text


async def stream_final_answer(messages: list[dict]) -> AsyncIterator[str]:
    """终答：不传 tools，流式逐 token yield 文本。"""
    client = get_client()
    t0 = time.time()
    _log.info(
        f"llm_stream_start provider={settings.llm_provider} model={settings.llm_model} stream=true "
        f"message_count={len(messages)} tool_enabled=false"
    )
    try:
        stream = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            stream=True,
            **_common_kwargs(),
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                yield text
    except Exception as e:  # noqa: BLE001
        _log.error(f"llm_error stage=stream error={e!r}")
        if not (_is_provider_risk_error(e) and settings.azure_fallback_configured):
            raise
        _log.warning(
            f"llm_fallback_start from_provider=dashscope to_provider=azure "
            f"reason=data_inspection_failed model={settings.azure_openai_deployment} stage=stream"
        )
        stream = await get_azure_client().chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages,
            stream=True,
            **_azure_kwargs(),
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                yield text
    dur = int((time.time() - t0) * 1000)
    _log.info(f"llm_stream_end duration_ms={dur}")
