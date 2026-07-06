"""Step 0 Day-1 冒烟（plan §16）：验证 DashScope qwen3.7-max
存在且支持 非流式 / 流式 / tool calling。

运行：
    RUN_LLM_TESTS=1 python scripts/test_openrouter_basic.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import AsyncOpenAI  # noqa: E402

from app.config import settings  # noqa: E402
from app.agent.tool_schemas import TOOLS  # noqa: E402


def _client() -> AsyncOpenAI:
    assert settings.llm_configured, "DashScope 未配置"
    return AsyncOpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )


def _common_kwargs() -> dict:
    kwargs = {"extra_body": {"enable_thinking": settings.dashscope_enable_thinking}}
    if settings.dashscope_max_tokens > 0:
        kwargs["max_tokens"] = settings.dashscope_max_tokens
    return kwargs


async def test_non_stream():
    print("[1/3] 非流式 ...")
    c = _client()
    resp = await c.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": "用一句话回答：1+1=?"}],
        stream=False,
        **_common_kwargs(),
    )
    content = resp.choices[0].message.content
    assert content, "非流式返回为空"
    print("    ✓ 非流式 OK:", content.strip()[:60])
    if resp.usage:
        print("    usage:", resp.usage)


async def test_stream():
    print("[2/3] 流式 ...")
    c = _client()
    stream = await c.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": "数到5，用逗号分隔。"}],
        stream=True,
        **_common_kwargs(),
    )
    parts = []
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            parts.append(chunk.choices[0].delta.content)
    text = "".join(parts)
    assert text, "流式无输出"
    print("    ✓ 流式 OK:", text.strip()[:60])


async def test_tools():
    print("[3/3] tool calling ...")
    c = _client()
    resp = await c.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user",
                   "content": "请查询剧本第8场的摘要。"}],
        tools=TOOLS,
        tool_choice="auto",
        stream=False,
        **_common_kwargs(),
    )
    msg = resp.choices[0].message
    tool_calls = msg.tool_calls or []
    assert tool_calls, "模型未发起 tool call（slug 可能不支持 function calling）"
    print(f"    ✓ tool calling OK: {tool_calls[0].function.name} "
          f"args={tool_calls[0].function.arguments[:80]}")


async def main():
    print(f"模型: {settings.llm_model}")
    print(f"base_url: {settings.dashscope_base_url}")
    await test_non_stream()
    await test_stream()
    await test_tools()
    print("\n✅ DashScope 冒烟全部通过：qwen3.7-max 可用，支持流式 + tool calling。")


if __name__ == "__main__":
    asyncio.run(main())
