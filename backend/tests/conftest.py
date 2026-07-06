"""pytest 全局配置：确保 backend 根目录在 sys.path 上，且离线测试不依赖 .env。"""
import os
import sys
from pathlib import Path

# backend/ 根目录加入 path，使 `import app...` 可用
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 离线测试用固定阈值，避免依赖外部 .env 内容
os.environ.setdefault("CHARS_PER_TOKEN", "2")
os.environ.setdefault("MAX_TOOL_CHARS", "12000")
os.environ.setdefault("MAX_TOOL_ESTIMATED_TOKENS", "3000")
os.environ.setdefault("MAX_CONTENT_FIELD_CHARS", "8000")
os.environ.setdefault("MAX_REGEX_LENGTH", "50")
os.environ.setdefault("DEFAULT_TOOL_LIMIT", "20")
os.environ.setdefault("MAX_TOOL_ROWS", "50")
os.environ.setdefault("KEEP_LATEST_TOOL_MESSAGES", "4")
os.environ.setdefault("LOG_DIR", "logs")
os.environ["REDIS_URL"] = ""
os.environ["HISTORY_PERSIST_MONGO"] = "false"
os.environ["HISTORY_REDIS_REQUIRED"] = "false"
