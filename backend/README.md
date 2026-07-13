# 剧本问答 Agent — 后端（FastAPI）

自写 Tool Loop 的剧本问答服务：AsyncOpenAI(指向阿里云百炼 OpenAI 兼容模式) + pymongo(run_in_threadpool) + SSE 仅终答流式。

## 环境要求

- **Python 3.10+**（本仓库用 `python3.12`；系统自带 3.9 跑不了 3.10+ 语法）
- 一个阿里云百炼 API Key、一个可访问的 MongoDB

## 安装

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 然后填入真实 key / mongo
```

> `httpx` 固定 `0.27.2`：openai 1.51 与 httpx>=0.28 的 `proxies` 参数不兼容，否则启动即报 `unexpected keyword argument 'proxies'`。

## 配置（.env）

关键项见 `.env.example`。当前真实库：

```env
DASHSCOPE_BASE_URL=https://llm-sun9d4d50ex0o5wu.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.7-max
DASHSCOPE_ENABLE_THINKING=false
MONGO_DB=serverless
```

两张工具表（都按 `script_id` + `is_deleted=0` 过滤，系统自动注入）：

| collection | 用途 | 关键字段 |
|---|---|---|
| `seca_gen_scene_outline` | 剧本原文 | scene_sort / scene_title / scene_summary / **content_text**(由 contents 拼接) |
| `seca_element_type_detail` | 元素(人物/服装/化妆/道具/场景) | element_type_code / element_name / remark |

`element_type_code` 枚举：`main_cast`(主要人物) `supporting_cast`(次要人物) `background_actor`(群演) `props_action`(动作道具) `props_static`(静态道具) `location`(地点) `costume`(服装) `makeup`(化妆) `special_effects`(特效)。

## 启动

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

> History 热数据优先存 Redis（未配置或非必需且不可用时回退进程内存），并可异步持久化到 MongoDB；使用内存回退时，`--reload` 或多 worker 不共享 history。

## 接口

- `POST /api/chat/stream` — SSE 流式问答（事件：status / tool_start / tool_result / delta / done / error）
- `POST /api/chat` — 非流式（内部消费流式，返回完整终答）
- `POST /api/debug/tool` — 直接执行一次工具查询
- `GET /api/debug/history/{session_id}` / `POST .../clear` — 查看 / 清空会话
- `GET /health` — 健康检查（含 mongo/llm 是否已配置）

curl 示例见仓库根 `DEV_PLAN.md` §19。

## 测试（真测，无假数据）

```bash
# 离线纯逻辑（113 用例：guard/budget/formatter/compactor/history/agent-loop-mock 等）
.venv/bin/python -m pytest tests -q

# 三档回归
bash scripts/run_all_tests.sh                                     # 离线 + 真实 Mongo
RUN_LLM_TESTS=1 bash scripts/run_all_tests.sh                     # + DashScope Qwen 冒烟 + 真实 Agent Loop
RUN_LLM_TESTS=1 RUN_STREAM_TESTS=1 bash scripts/run_all_tests.sh  # + HTTP SSE(需先启动后端)
```

单跑脚本：

| 脚本 | 说明 | 依赖 |
|---|---|---|
| `scripts/test_openrouter_basic.py` | Day-1 冒烟：验证 DashScope qwen3.7-max 非流式/流式/tool calling | LLM |
| `scripts/test_mongo_connection.py` | 连接 + 两张工具表字段结构 | Mongo |
| `scripts/test_mongo_tool.py` | 真实查询/拒绝/limit/截断（真 script_id） | Mongo |
| `scripts/test_agent_tool_loop.py` | 真实 Agent Loop 多轮+指代 | LLM+Mongo |
| `scripts/test_stream_api.py` | /api/chat/stream HTTP SSE（头/事件/流式） | 已启动后端 |
| `scripts/test_local_history.py` / `test_history_compaction.py` | 历史/压缩 | 离线 |
| `scripts/explore_mongo.py` / `explore_mongo2.py` | 一次性数据探查（开发期用） | Mongo |

真实测试默认剧本：`script_id=6a4f56a54bc764f6d3181d83`（两张工具表齐全）。

## 日志（plan §14）

`logs/` 下分域：`app.log` / `llm.log` / `tool.log` / `history.log` + `conversation_events.jsonl`（完整对话流水）。
每条带 `trace_id / session_id / script_id`（contextvar 在请求入口注入，贯穿全链路）。

## 三层 token 防护

1. 单结果太大 → 32K 字符 / 16K 估算 token 的 tool budget 硬截断 `[TOOL_RESULT_TRUNCATED]`（content 字段 8K 字符，字段级 `[FIELD_TRUNCATED]`）
2. 单次提问查太多轮 → `MAX_TOOL_ROUNDS=15` + 终答 `tool_choice=none`
3. session 历史堆积 → 旧 tool 消息压缩 `[TOOL_RESULT_COMPRESSED]`（保留最近 `KEEP_LATEST_TOOL_MESSAGES=4`），会话输入预算按 500K token 管理

Mongo 查询默认最多 20 行、总上限 50 行；查询 content 字段时 `CONTENT_QUERY_LIMIT_MAX=50`。

## 排查

- **启动报 `proxies`** → httpx 版本不对，`pip install httpx==0.27.2`
- **流式一卡一坨** → 确认前端直连 8000、SSE 头含 `X-Accel-Buffering: no`、未经反代缓冲
- **多轮指代/历史丢失** → 是否 `--reload` 改了代码或开了多 worker（内存 history 被清/不共享）
- **Mongo 连不上** → standalone 用 `directConnection=true`；`authSource=admin`
