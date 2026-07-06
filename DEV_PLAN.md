# 本地 Mac 第一版开发计划（最终版）

> 本版已纳入流式 / 异步 / Mongo / 轮数与压缩的最终决策。
> 核心决策摘要见 [§0 关键决策](#0-关键决策固定不再讨论)，开发时以此为准。

---

## 0. 关键决策（固定，不再讨论）

| 主题 | 最终决策 | 原因 |
|---|---|---|
| 流式范围 | **仅终答流式**：工具轮非流式，最终回答 `stream=True` 逐 token 输出 | MVP 够用，工具轮只发 status |
| LLM 客户端 | **AsyncOpenAI**（指向 OpenRouter），禁用同步客户端 | 同步客户端会阻塞事件循环，导致流“一卡一卡” |
| Mongo 客户端 | **pymongo 同步工具 + 调用处 `run_in_threadpool`**，不用 motor，也不用 AsyncMongoClient | motor 已弃用；工具是纯同步逻辑，包一层即可，测试脚本零改动 |
| SSE 不缓冲 | 响应头加 `Cache-Control: no-cache` / `X-Accel-Buffering: no`；前端**直连** 8000，不经 Next.js 转发 | 转发层默认缓冲流，会破坏流式 |
| token 粗估 | 中文用 `len(content) // 2`（不是 //4） | 中文约 1.3~2 char/token，//4 会严重低估、预算约束形同虚设 |
| 工具轮收尾 | 到 `MAX_TOOL_ROUNDS` 时终答调用 **`tool_choice="none"`**，强制出文本 | 否则模型可能在流式终答里又返回 tool_calls，得到半截/空回答 |
| 模型 slug | Day-1 先用 `test_openrouter_basic.py` 验证 `openai/gpt-5.5` 真实存在且支持 tool calling + streaming | 模型名错或不支持 function calling，整个 Loop 白搭 |

### 三层 token 防护（各管一摊，互不打架）

```text
单个工具结果太大   → tool budget 硬截断   → [TOOL_RESULT_TRUNCATED]
单次提问查太多轮   → MAX_TOOL_ROUNDS=4 + 终答 tool_choice=none
session 历史堆积   → 工具消息压缩         → [TOOL_RESULT_COMPRESSED]
```

> 注意两个独立的“4”，不要混：
> - `MAX_TOOL_ROUNDS=4`：**单次提问内**的工具循环上限。
> - `KEEP_LATEST_TOOL_MESSAGES=4`：**整个 session 跨多次提问**的历史压缩，只压旧结果，不影响新问题继续调工具。

---

## 1. 第一版范围

### 技术栈

| 模块 | 选型 |
|---|---|
| 后端 API | FastAPI |
| 前端 | Next.js + React |
| LLM API | OpenRouter |
| LLM 模型 | `openai/gpt-5.5`（Day-1 验证） |
| LLM 客户端 | **AsyncOpenAI** |
| Agent | 自写 Tool Loop |
| 流式输出 | SSE（仅终答流式） |
| 数据查询 | MongoDB Tool（**pymongo + run_in_threadpool**） |
| History | 本地内存 + 本地 JSONL 日志 |
| 测试 | pytest + scripts |
| 日志 | loguru / logging |

### 第一版不做

```text
LangGraph / Redis / COS / 云部署 / Serverless
Mongo 存会话 history / 复杂权限 / 向量检索 / 生产级鉴权
motor / AsyncMongoClient
工具轮的中间文本流式（仅终答流式）
```

---

## 2. 目标架构

```text
Next.js Chat 页面 ──直连──> FastAPI /api/chat/stream
                                  ↓
                            自写 Agent Loop
                          ┌───────┴────────┐
                工具轮(非流式)            终答(流式)
          AsyncOpenAI gpt-5.5      AsyncOpenAI gpt-5.5
                ↓                    tool_choice="none"
        execute_mongo_query                ↓
   (pymongo, run_in_threadpool)      逐 token delta SSE
                ↓
        MongoDB 三张剧本表
                ↓
        Tool budget 截断 → tool_result SSE
                          ↓
              本地内存 history + JSONL 日志 + 压缩
```

---

## 3. 项目结构

```text
script-agent-mvp/
  ├── backend/
  │   ├── app/
  │   │   ├── main.py
  │   │   ├── config.py
  │   │   ├── schemas.py
  │   │   ├── logging_config.py
  │   │   ├── api/        { chat.py, debug.py, health.py }
  │   │   ├── agent/      { loop.py, prompts.py, openrouter_client.py,
  │   │   │                tool_schemas.py, stream_events.py }
  │   │   ├── tools/      { mongo_query_tool.py, mongo_guard.py,
  │   │   │                budget.py, formatter.py }
  │   │   ├── history/    { local_history_store.py, compactor.py }
  │   │   ├── db/         { mongo_client.py }
  │   │   └── utils/      { ids.py, json_utils.py }
  │   ├── scripts/        { test_*.py, run_all_tests.sh }
  │   ├── tests/          { test_*.py }
  │   ├── logs/           { app/llm/tool/history.log, conversation_events.jsonl }
  │   ├── requirements.txt
  │   ├── .env  /  .env.example
  │   └── README.md
  └── frontend/
      ├── app/           { page.tsx, layout.tsx }
      ├── components/     { ChatPage, MessageList, ChatInput, ToolMessage, ToolStatus }
      ├── lib/           { chatStream.ts, session.ts }
      ├── package.json
      └── next.config.js
```

---

## 4. 后端依赖（`backend/requirements.txt`）

```txt
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.9.2
pydantic-settings==2.5.2
pymongo==4.9.1
openai==1.51.2          # 用 AsyncOpenAI
python-dotenv==1.0.1
loguru==0.7.2
pytest==8.3.3
pytest-asyncio==0.24.0
```

> 用 `AsyncOpenAI` 调 OpenRouter，**不再手搓 httpx**，故移除 httpx 依赖（如个别脚本需要可单独装）。

---

## 5. 环境变量（`backend/.env`）

```env
APP_ENV=local
APP_HOST=0.0.0.0
APP_PORT=8000

OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=openai/gpt-5.5

MONGO_URI=mongodb://user:password@host:27017/db?authSource=admin
MONGO_DB=your_db

MAX_TOOL_ROUNDS=4
DEFAULT_TOOL_LIMIT=20
MAX_TOOL_ROWS=50
MAX_TOOL_CHARS=12000
MAX_TOOL_ESTIMATED_TOKENS=3000
MAX_REGEX_LENGTH=50
MAX_CONTENT_FIELD_CHARS=8000
MONGO_MAX_TIME_MS=5000

KEEP_LATEST_TOOL_MESSAGES=4

# token 粗估系数：中文场景用 2（len // CHARS_PER_TOKEN）
CHARS_PER_TOKEN=2

LOG_LEVEL=INFO
LOG_DIR=logs

# CORS：前端直连
CORS_ORIGINS=http://localhost:3000
```

---

## 6. 接口设计

### 6.1 流式聊天 `POST /api/chat/stream`

请求：

```json
{ "session_id": "sess_xxx", "script_id": "script_001", "question": "第8场发生了什么？" }
```

SSE 事件序列（工具轮只发 status / tool_*，终答阶段才发 delta）：

```text
event: status        data: {"message":"正在分析问题..."}
event: tool_start    data: {"tool_call_id":"call_x","tool_name":"execute_mongo_query","purpose":"查询第8场摘要"}
event: tool_result   data: {"tool_call_id":"call_x","tool_name":"...","purpose":"...","preview":"前200字...","full_result":"硬截断后的完整结果","truncated":false,"estimated_tokens":320,"truncation_reason":null}
event: delta         data: {"text":"第8场中，"}          # 仅终答阶段
event: done          data: {"session_id":"sess_xxx"}
event: error         data: {"message":"错误信息"}
```

**SSE 响应头（强制）：**

```python
StreamingResponse(
    gen(),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    },
)
```

### 6.2 非流式 `POST /api/chat`
### 6.3 Tool Debug `POST /api/debug/tool`

```json
{
  "script_id": "script_001",
  "args": {
    "collection": "script_scene_summary",
    "operation": "find",
    "filter": { "scene_no": 8 },
    "projection": { "_id": 0, "scene_no": 1, "summary": 1 },
    "limit": 10,
    "purpose": "调试第8场摘要"
  }
}
```

### 6.4 History Debug `GET /api/debug/history/{session_id}`
### 6.5 清空 History `POST /api/debug/history/{session_id}/clear`
### 6.6 健康检查 `GET /health`

---

## 7. 前端功能要求

### 7.1 页面功能

```text
ChatGPT 风格消息列表 / 输入框 / 发送按钮 / + New Chat 按钮
流式显示 assistant 回答
tool 独占一行（tool_name + purpose + preview 200 字）
tool result 展开/收起
显示 status / error
```

### 7.2 New Chat 行为

```text
点击 + New Chat → 生成新 session_id → 清空 messages → 清空 streaming 状态
→ 后续请求用新 session_id → 后端读到新的空 history
```

### 7.3 前端消息类型

```ts
export type ChatMessage = UserMessage | AssistantMessage | ToolMessage | StatusMessage;

export type UserMessage = { id: string; type: "user"; content: string };
export type AssistantMessage = { id: string; type: "assistant"; content: string; streaming?: boolean };
export type ToolMessage = {
  id: string; type: "tool"; toolName: string; purpose: string;
  preview: string; fullResult: string; expanded: boolean;
  truncated?: boolean; estimatedTokens?: number; truncationReason?: string | null;
};
export type StatusMessage = { id: string; type: "status"; content: string };
```

### 7.4 流式渲染注意

`delta` 高频到达时**不要每个 token 重渲染整个列表**：用 ref 累加文本 + 节流（如 rAF / 30ms）刷新当前 assistant 气泡，长回答才不卡。

---

## 8. Tool 设计

- 名称：`execute_mongo_query`
- 可查 collection：`script_scene_original` / `script_scene_summary` / `script_assets_unified`
- 支持操作：`find` / `count`
- 禁止：`insert/update/delete/drop/aggregate/createIndex` 及 `$out/$merge/$where/$function/$accumulator`

### Tool Schema

```python
TOOLS = [{
  "type": "function",
  "function": {
    "name": "execute_mongo_query",
    "description": "查询剧本 MongoDB 数据库，只允许只读查询。用于检索剧本原文、分场摘要、人物、服装、化妆、道具和场景信息。",
    "parameters": {
      "type": "object",
      "properties": {
        "collection": {"type": "string",
          "enum": ["script_scene_original","script_scene_summary","script_assets_unified"],
          "description": "要查询的 collection"},
        "operation": {"type": "string", "enum": ["find","count"], "description": "查询类型"},
        "filter": {"type": "object", "description": "Mongo 查询条件，不需要传 script_id，系统会自动注入"},
        "projection": {"type": "object", "description": "返回字段"},
        "sort": {"type": "object", "description": "排序条件"},
        "limit": {"type": "integer", "description": "最大返回条数，最大 50"},
        "purpose": {"type": "string", "description": "本次查询目的"}
      },
      "required": ["collection","operation","purpose"]
    }
  }
}]
```

---

## 9. Mongo Tool 硬约束

### 9.1 查询约束

```text
只允许 find/count；collection 必须白名单内
强制注入 script_id
默认 limit=20；最大 limit=50；查 content 时 limit 最大 10
maxTimeMS=5000；projection 默认 {"_id":0}
禁止危险 operator；禁止超长 regex（> MAX_REGEX_LENGTH）
```

### 9.2 预算约束

```text
MAX_TOOL_ROWS=50
MAX_TOOL_CHARS=12000
MAX_TOOL_ESTIMATED_TOKENS=3000
MAX_CONTENT_FIELD_CHARS=8000
```

token 粗估（**中文用 //2**）：

```python
estimated_tokens = max(1, len(content) // CHARS_PER_TOKEN)   # CHARS_PER_TOKEN=2
hard_max_chars   = min(MAX_TOOL_CHARS, MAX_TOOL_ESTIMATED_TOKENS * CHARS_PER_TOKEN)
```

> 上线前用一次真实 usage 校准 `CHARS_PER_TOKEN`（拿模型返回的 prompt_tokens 反推系数）。

### 9.3 截断标记

```text
[FIELD_TRUNCATED] / [TOOL_RESULT_TRUNCATED] / [TOOL_RESULT_COMPRESSED]
```

### 9.4 Tool Result 格式

> **截断只切尾部**（content 放最后），绝不截断前面的 JSON 结构，避免模型读到坏 JSON。

未截断：

```text
MONGO_RESULT
collection: script_scene_summary
operation: find
purpose: 查询第8场摘要
row_count: 1
truncated: false
estimated_tokens: 320

[ { "scene_no": 8, "summary": "……" } ]
```

已截断：

```text
MONGO_RESULT
collection: script_scene_original
operation: find
purpose: 查询包含戒指的原文
row_count_returned: 10
truncated: true
truncation_reason: tool_message_budget_exceeded
estimated_tokens_before_truncate: 8600
estimated_tokens_after_truncate: 3000

notice:
结果已被硬截断。不要基于截断结果做过度推断。
如需更准确细节，请重新调用 execute_mongo_query，用更具体的 scene_no/人物/地点/关键词缩小范围。

content:
……
[TOOL_RESULT_TRUNCATED]
```

---

## 10. History 设计

- 存储：本地内存 `active_history` + 本地 JSONL 完整流水
- 内存结构：

```python
SESSION_HISTORY = { "sess_001": [ {"role":"user","content":"..."}, {"role":"assistant","content":"..."} ] }
```

- JSONL：`backend/logs/conversation_events.jsonl`，每行：

```json
{"trace_id":"trace_001","session_id":"sess_001","script_id":"script_001","role":"user","message":{"role":"user","content":"第8场发生了什么？"}}
```

> ⚠️ 内存 history 在 `uvicorn --reload`（改代码即清空）和 `--workers>1`（进程不共享）下会丢。**开发联调期固定单进程、联调时不改后端代码。** 已在 README 注明。

---

## 11. Tool Message 压缩

规则：

```text
最近 KEEP_LATEST_TOOL_MESSAGES(=4) 个 role=tool 消息保留完整
更早的 role=tool 消息替换为 [TOOL_RESULT_COMPRESSED]
assistant tool_calls 不删除；tool_call_id 不修改
消息顺序不变；消息总数不减少
```

占位符：

```text
[TOOL_RESULT_COMPRESSED]
早期 Mongo 查询结果已从当前上下文中压缩，不能作为精确事实依据。
如后续问题需要准确细节，请重新调用 execute_mongo_query 查询。
```

---

## 12. Agent Loop 流程（最终版）

```text
收到 /api/chat/stream
  ↓ 生成 trace_id
  ↓ 写 user message 到 local history
  ↓ 读取 active_history，构造 system + history + question
  ↓ 发送 status SSE：正在分析问题
  ↓
for round in range(MAX_TOOL_ROUNDS):
    resp = await AsyncOpenAI.create(messages, tools=TOOLS, stream=False)   # 工具轮非流式
    if not resp.tool_calls: break          # 模型决定直接回答
    for tc in resp.tool_calls:
        发送 tool_start SSE
        result = await run_in_threadpool(execute_mongo_query, script_id, args)  # pymongo 不阻塞
        result = enforce_tool_budget(result)   # 硬截断
        发送 tool_result SSE
        append assistant(tool_calls) + tool message
  ↓ （循环到顶仍要工具 → 直接进入终答，不再给工具）
  ↓
终答：async for chunk in AsyncOpenAI.create(messages, tool_choice="none", stream=True):
        逐 token 发送 delta SSE
  ↓ 收集完整 assistant answer
  ↓ 写 assistant message 到 local history
  ↓ 写 conversation_events.jsonl
  ↓ 执行 tool message 压缩（KEEP_LATEST=4）
  ↓ 发送 done SSE
```

**核心实现点：**
1. 工具轮 `stream=False`，终答 `stream=True` 且 `tool_choice="none"`。
2. 终答流式需累加文本；若改成工具轮也流式，则要写 tool_calls 分片累加器——本版不做。
3. Mongo 调用一律走 `run_in_threadpool`。

---

## 13. System Prompt

```text
你是一个专业剧本问答助手。你可以调用 execute_mongo_query 查询剧本数据库。

你必须遵守：
1. 不要编造剧本内容。
2. 询问具体剧情、人物、服装、化妆、道具、场景时，应优先调用工具查询。
3. 查故事脉络、剧情概括、人物变化 → 优先 script_scene_summary。
4. 查原文、台词、具体动作 → 优先 script_scene_original。
5. 查人物、服装、化妆、道具、场景 → 优先 script_assets_unified。
6. 查询尽量小范围、高效率，不要一次请求全剧原文或大量 content。
7. 能用 scene_no/人物/地点/道具关键词缩小范围的，先缩小范围。
8. 遇到“他、她、那场、当时、刚才”等指代，结合历史消息理解。
9. 历史出现 [TOOL_RESULT_COMPRESSED] → 旧结果已压缩，不能作精确依据，需要细节就重新查。
10. 工具结果出现 [TOOL_RESULT_TRUNCATED] → 已硬截断，不能作完整依据。
11. 需要更准确信息 → 重新调用工具并用更具体 filter。
12. 回答时尽量说明依据（第几场、摘要或原文）。
13. 资料不足时明确说明无法从当前资料确认。
14. 依据来自截断结果时，明确说明资料可能不完整。
15. 当资料已足够、或已无法继续查询时，用现有信息直接作答（不要再尝试调用工具）。
```

> 第 15 条配合终答 `tool_choice="none"`，确保轮数到顶能干净收尾。

---

## 14. 日志计划

文件：`logs/{app,llm,tool,history}.log` + `logs/conversation_events.jsonl`

通用字段：`trace_id / session_id / script_id / event / duration_ms`
（建议用 `contextvar` 在请求入口统一注入 trace_id / session_id，贯穿所有日志）

- **app.log**：request_start/end、stream_start/done/error、api_error
- **llm.log**：llm_call_start/end、llm_stream_start/end、llm_error、tool_call_detected
  字段：`model / stream / message_count / tool_enabled / has_tool_calls / tool_call_count / duration_ms`
- **tool.log**：tool_call_start/end、tool_guard_reject、tool_result_budget、tool_error
  字段：`collection / operation / purpose / limit_requested / limit_final / row_count / field_truncated / tool_message_truncated / estimated_tokens_before / estimated_tokens_after / truncation_reason / preview_200 / duration_ms`
- **history.log**：history_load/append/replace/clear/compaction、conversation_event_write
  字段：`message_count_before/after / tool_messages_total / tool_messages_compressed / keep_latest_tool_messages`

---

## 15. 自动化测试计划

### scripts（端到端 / 需外部依赖）

```text
test_mongo_connection.py   # 连接 + 三表各取一条 + 打印字段结构
test_mongo_tool.py         # 正常查询 + 非法 collection/operation/$where 拒绝
                           # limit=999→50 / content 查询 limit→10 / 超 CHARS 截断 / 超 token 截断
                           # truncated=true / estimated_tokens_after / preview≤200
test_openrouter_basic.py   # ★Day-1：非流式 + 流式 + 带 tools 调用 gpt-5.5，验证 slug 有效
test_agent_tool_loop.py    # 触发 tool call / 执行 / tool result 入 messages / 终答非空 / 截断 notice 可见
test_stream_api.py         # /api/chat/stream 收到 status / tool_result(含 preview/full_result) / done
test_local_history.py      # 空 history / append user&assistant&tool / 顺序 / JSONL 写入 / clear / session 隔离
test_history_compaction.py # >4 tool message → 只留最近 4 完整，旧的替换，tool_call_id/顺序/总数不变
run_all_tests.sh
```

### pytest（纯逻辑 / 可离线）

```text
test_mongo_guard.py    # 白名单 / 危险 operator / 超长 regex / limit normalize / script_id 强制注入
test_tool_budget.py    # estimate_tokens=len//CHARS_PER_TOKEN / 小文本不截 / 超 CHARS 截 / 超 token 截
                       #   截断含 [TOOL_RESULT_TRUNCATED] / 大字段含 [FIELD_TRUNCATED] / after 不超预算太多
test_compactor.py      # ≤4 不压 / >4 留最近4 / 旧 content 被替换 / tool_call_id 不变 / 总数顺序不变
test_formatter.py      # 格式正确 / truncated&estimated_tokens 字段 / preview≤200 / 中文 JSON 序列化正常
test_agent_loop_mock.py# mock LLM 返回 tool_calls→执行 / tool message 追加 / 无 tool_calls 直接答
                       #   超 MAX_TOOL_ROUNDS 停止并终答 / 工具异常返回 error
```

### `scripts/run_all_tests.sh`

```bash
#!/usr/bin/env bash
set -e
echo "Running pytest...";            pytest tests -q
echo "Testing Mongo connection..."; python scripts/test_mongo_connection.py
echo "Testing Mongo tool...";       python scripts/test_mongo_tool.py
echo "Testing history compaction..."; python scripts/test_history_compaction.py
echo "Testing local history...";    python scripts/test_local_history.py

if [ "$RUN_LLM_TESTS" = "1" ]; then
  echo "Testing OpenRouter basic..."; python scripts/test_openrouter_basic.py
  echo "Testing agent tool loop..."; python scripts/test_agent_tool_loop.py
fi
if [ "$RUN_STREAM_TESTS" = "1" ]; then
  echo "Testing stream API..."; python scripts/test_stream_api.py
fi
echo "All tests passed."
```

---

## 16. 开发步骤（按此顺序）

> **Step 0（Day-1 冒烟，最先做）：** 验证 `openai/gpt-5.5` 在 OpenRouter 上存在且支持 tool calling + streaming。
> 写 `test_openrouter_basic.py` 跑通三件事：非流式、流式、带 tools。slug 不对就先解决，别往下走。

| # | 阶段 | 关键交付 | 验证 |
|---|---|---|---|
| 0 | OpenRouter 冒烟 | 验证 gpt-5.5 + AsyncOpenAI 跑通 | `RUN_LLM_TESTS=1 python scripts/test_openrouter_basic.py` |
| 1 | FastAPI 骨架 + 假流式 | health / chat / chat/stream + 假 SSE + SSE 不缓冲头 | `python scripts/test_stream_api.py` |
| 2 | Next.js Chat 页面 | 消息列表 / 输入 / New Chat / ToolMessage 展示 / 直连 8000 | 前端展示假流式 + tool 独占行 + New Chat 换 session |
| 3 | Mongo 连接 | mongo_client + 三表样例字段 | `python scripts/test_mongo_connection.py` |
| 4 | Guard + Budget | 白名单 / operator / regex / limit normalize / estimate_tokens / 截断 | `pytest tests/test_mongo_guard.py tests/test_tool_budget.py` |
| 5 | Mongo Tool + Formatter + Debug API | execute_mongo_query（同步）/ script_id 注入 / maxTimeMS / 截断 / preview / /api/debug/tool | `python scripts/test_mongo_tool.py` + `pytest tests/test_formatter.py` |
| 6 | OpenRouter Client | **AsyncOpenAI** 非流式 + 流式 + tools + 错误处理 + llm.log | `RUN_LLM_TESTS=1 python scripts/test_openrouter_basic.py` |
| 7 | 自写 Agent Loop | 工具轮非流式 / 终答 stream + tool_choice=none / run_in_threadpool 调 Mongo / MAX_TOOL_ROUNDS 收尾 | `pytest tests/test_agent_loop_mock.py` + `RUN_LLM_TESTS=1 python scripts/test_agent_tool_loop.py` |
| 8 | Local History | get/append/replace/clear + JSONL + session 隔离 | `python scripts/test_local_history.py` |
| 9 | Tool Message 压缩 | KEEP_LATEST=4 / 旧→COMPRESSED / tool_call_id/顺序/总数不变 | `pytest tests/test_compactor.py` + `python scripts/test_history_compaction.py` |
| 10 | 前后端真实联调 | 真实 stream / Mongo / tool_start&result / 终答流式 / New Chat / 多轮追问 / 截断可见 | 见 §17 联调问题集 |
| 11 | 回归测试 | 三档 run_all_tests | 见下 |
| 12 | 文档 | README + .env.example + 启动/测试/日志/排查说明 | — |

回归三档：

```bash
bash scripts/run_all_tests.sh
RUN_LLM_TESTS=1 bash scripts/run_all_tests.sh
RUN_LLM_TESTS=1 RUN_STREAM_TESTS=1 bash scripts/run_all_tests.sh
```

---

## 17. 联调问题集（Step 10 用）

```text
第8场发生了什么？          这个剧本讲什么？        主线冲突是什么？
第12场有哪些人物？         女主穿什么？            第8场女主穿什么？
戒指出现在哪些场？         她当时穿什么？          这个道具后面还出现了吗？
```

重点观察：
- 终答是否逐 token 流式（不是攒一坨）；
- 指代（“她/当时/那场”）能否结合历史；
- 大范围查询是否被截断且前端可见 `truncated / estimated_tokens / truncation_reason`；
- 多轮后旧工具结果被压成 `[TOOL_RESULT_COMPRESSED]`，新问题仍能正常重新查询。

---

## 18. 本地启动

后端：

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000     # 联调期单进程，勿改后端代码以免清空内存 history
```

前端：

```bash
cd frontend
npm install && npm run dev
```

访问：前端 `http://localhost:3000`，后端 `http://localhost:8000`

---

## 19. curl 测试

```bash
# 健康检查
curl http://localhost:8000/health

# 流式聊天（-N 关闭 curl 缓冲）
curl -N -X POST "http://localhost:8000/api/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"sess_test_001","script_id":"script_001","question":"第8场发生了什么？"}'

# Tool Debug
curl -X POST "http://localhost:8000/api/debug/tool" \
  -H "Content-Type: application/json" \
  -d '{"script_id":"script_001","args":{"collection":"script_scene_summary","operation":"find","filter":{"scene_no":8},"projection":{"_id":0,"scene_no":1,"summary":1},"limit":10,"purpose":"调试第8场摘要"}}'
```

---

## 20. 最终验收标准

```text
环境
 1. 后端 FastAPI 可本地启动。
 2. 前端 Next.js 可本地启动。
 3. LLM 模型使用 openai/gpt-5.5（Day-1 已验证 slug 有效）。
 4. LLM 客户端为 AsyncOpenAI，终答流式不卡顿。

前端
 5. 有 + New Chat 按钮；点击后生成新 session_id、消息清空。
 6. 能流式显示 assistant 回答（逐 token，不攒批）。
 7. tool 独占一行，显示 tool_name / purpose / preview。
 8. tool result 默认显示 200 字，可展开。
 9. tool 行显示 truncated / estimated_tokens / truncation_reason。

Agent / 流式
10. 不使用 LangGraph。
11. 工具轮非流式，终答 stream=True 且 tool_choice="none"。
12. LLM 能自主调用 execute_mongo_query。
13. 到 MAX_TOOL_ROUNDS 能强制出终答，不死循环。

Mongo Tool
14. 只能 find/count；只能查白名单 collection。
15. 强制注入 script_id。
16. limit 最大 50；查 content 时 limit 最大 10。
17. 设置 maxTimeMS；禁止危险 operator；禁止超长 regex。
18. Mongo 调用走 run_in_threadpool，不阻塞事件循环。

预算 / 截断
19. 单字段超长截断（[FIELD_TRUNCATED]）。
20. 超 MAX_TOOL_CHARS / 超 MAX_TOOL_ESTIMATED_TOKENS 截断（[TOOL_RESULT_TRUNCATED]）。
21. token 粗估 = len // CHARS_PER_TOKEN（中文 =2）。

History / 压缩
22. 第一版用本地内存 + JSONL。
23. 最近 4 个 tool message 保留完整，更早替换为 [TOOL_RESULT_COMPRESSED]。
24. assistant tool_calls 不删除；tool_call_id / 顺序 / 总数不变。

日志 / 测试
25. 日志覆盖 app / llm / tool / history。
26. 自动化测试覆盖 Mongo / Tool / Budget / Guard / LLM / Agent Loop / Stream / History / Compactor。
27. run_all_tests.sh 三档可执行回归。
```

---

## 21. 执行顺序总表

```text
0.  ★ OpenRouter 冒烟：验证 gpt-5.5 + AsyncOpenAI（最先做）
1.  FastAPI 骨架 + 假流式（含 SSE 不缓冲头）
2.  Next.js Chat 页面 + New Chat + ToolMessage 展示（直连 8000）
3.  Mongo 连接测试
4.  Mongo Guard + Tool Budget（中文 token 系数）
5.  Mongo Tool（同步）+ Formatter + Debug API
6.  OpenRouter Client（AsyncOpenAI）
7.  自写 Agent Loop（工具轮非流式 / 终答流式+tool_choice=none / run_in_threadpool）
8.  Local History Store
9.  Tool Message 压缩
10. 前后端真实联调
11. 自动化回归测试
12. README 与本地启动文档
```
