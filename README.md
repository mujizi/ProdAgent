# ProdAgent — 剧本问答 Agent（本地第一版）

自写 Tool Loop 的剧本问答系统：FastAPI 后端 + Next.js 前端，LLM 走阿里云百炼 OpenAI 兼容模式（`qwen3.7-max`），数据查询走 MongoDB 只读工具，终答 SSE 逐 token 流式。

开发计划与决策见 [`DEV_PLAN.md`](DEV_PLAN.md)。

## 架构

```
Next.js Chat 页面 ──直连──> FastAPI /api/chat/stream
                                  ↓ 自写 Agent Loop
                    工具轮(非流式)        终答(流式, 不传 tools)
                          ↓
                  execute_mongo_query (pymongo + run_in_threadpool)
                          ↓
                MongoDB 两张工具表(只读) → 预算硬截断 → SSE
                          ↓
               Redis/内存 history + Mongo 持久化 + JSONL + 旧结果压缩
```

## 快速启动

**0) 一键安装依赖**
```bash
git clone git@github.com:mujizi/ProdAgent.git
cd ProdAgent
bash scripts/install.sh
```

然后填写 `backend/.env` 里的真实密钥、Mongo、Redis 配置。

**1) 后端**（详见 [`backend/README.md`](backend/README.md)）
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填 DASHSCOPE_* / MONGO_URI / MONGO_DB
uvicorn app.main:app --reload --port 8000
```

**2) 前端**
```bash
cd frontend
npm install
npm run dev            # http://localhost:3000，直连后端 8000
```

前端通过 `NEXT_PUBLIC_API_BASE` 和 `NEXT_PUBLIC_SCRIPT_ID` 连接后端。当前源码 API fallback 为 `http://172.16.2.79:8000`；本机开发请显式设置 `NEXT_PUBLIC_API_BASE=http://localhost:8000`。

## Docker

先准备环境文件：
```bash
cp backend/.env.example backend/.env
# 填写 backend/.env
```

一键构建并运行镜像：
```bash
bash scripts/docker-run.sh
```

脚本默认使用国内镜像源：
- npm: `https://registry.npmmirror.com`
- pip: `https://pypi.tuna.tsinghua.edu.cn/simple`

如果你的机器访问官方源更稳定，可以覆盖：
```bash
NPM_REGISTRY=https://registry.npmjs.org \
PIP_INDEX_URL=https://pypi.org/simple \
bash scripts/docker-run.sh
```

默认暴露：
- 前端 `http://localhost:3000`
- 后端 `http://localhost:8000/health`

可覆盖参数：
```bash
BACKEND_PORT=18000 FRONTEND_PORT=13000 \
NEXT_PUBLIC_API_BASE=http://localhost:18000 \
SCRIPT_ID=6a4f56a54bc764f6d3181d83 \
USER_ID=dev_user_frontend \
bash scripts/docker-run.sh
```

## 功能

- ChatGPT 风格消息列表 / 输入 / **＋ New Chat**（新 session、清空消息）
- assistant 终答逐 token 流式（rAF 节流，长回答不卡）
- tool 独占一行：tool_name + purpose + preview，展开看完整结果，显示 truncated / estimated_tokens / truncation_reason
- 多轮追问 + 指代消解（"那场 / 她 / 当时" 结合历史）
- 工具循环最多 15 轮；单次工具结果预算为 32K 字符 / 16K 估算 token，content 查询最多 50 行
- 会话热历史使用 Redis（可回退内存），完整消息可持久化到 MongoDB，并按 500K token 输入窗口压缩

## 测试

后端真实测试（无假数据，默认剧本 `6a4f56a54bc764f6d3181d83`）：
```bash
cd backend
bash scripts/run_all_tests.sh                                     # 离线 + 真实 Mongo
RUN_LLM_TESTS=1 RUN_STREAM_TESTS=1 bash scripts/run_all_tests.sh  # 全量（需先启动后端）
```

## 现状

后端全链路已真实端到端验证（DashScope Qwen 冒烟 / 真实 Mongo 工具 / Agent Loop 多轮 / HTTP SSE / 离线 pytest），前端已用真实浏览器验证（流式 / tool 展示 / New Chat）。第一版范围与未做项见 `DEV_PLAN.md` §1。
