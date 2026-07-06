"""Tool 预算与截断（plan §9.2 / §9.3）。

三层 token 防护中的“单个工具结果太大 → 硬截断”。纯逻辑，可离线测。

- estimate_tokens(text) = max(1, len // CHARS_PER_TOKEN)
- 大字段截断（content 字段超 MAX_CONTENT_FIELD_CHARS）→ [FIELD_TRUNCATED]
- 整体结果超 MAX_TOOL_CHARS 或超 MAX_TOOL_ESTIMATED_TOKENS → 尾部截断 [TOOL_RESULT_TRUNCATED]
  （只切尾部 content，不破坏前面的结构）
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings

FIELD_TRUNCATED = "[FIELD_TRUNCATED]"
TOOL_RESULT_TRUNCATED = "[TOOL_RESULT_TRUNCATED]"
TOOL_RESULT_COMPRESSED = "[TOOL_RESULT_COMPRESSED]"


def estimate_tokens(content: str) -> int:
    """中文粗估：len // CHARS_PER_TOKEN（plan §9.2，CHARS_PER_TOKEN=2）。"""
    return max(1, len(content) // settings.chars_per_token)


def truncate_field(value: str) -> tuple[str, bool]:
    """截断单个超长字符串字段。返回 (新值, 是否截断)。"""
    limit = settings.max_content_field_chars
    if len(value) <= limit:
        return value, False
    return value[:limit] + f"\n{FIELD_TRUNCATED}", True


def truncate_rows_fields(rows: list[dict]) -> tuple[list[dict], bool]:
    """对每行的字符串字段做大字段截断。返回 (新 rows, 是否有任意字段被截)。"""
    any_truncated = False
    new_rows = []
    for row in rows:
        if not isinstance(row, dict):
            new_rows.append(row)
            continue
        new_row = {}
        for k, v in row.items():
            if isinstance(v, str):
                nv, t = truncate_field(v)
                new_row[k] = nv
                any_truncated = any_truncated or t
            else:
                new_row[k] = v
        new_rows.append(new_row)
    return new_rows, any_truncated


@dataclass
class BudgetResult:
    text: str
    truncated: bool
    estimated_tokens: int
    estimated_tokens_before: int
    truncation_reason: str | None


def enforce_tool_budget(body: str) -> BudgetResult:
    """对“最终拼好的工具结果文本的尾部内容”做整体预算硬截断。

    body 是放在结果尾部的 content（formatter 会把结构性头部与 body 分开拼接，
    这里只对 body 截断，保证前面的 JSON 结构不被破坏）。
    """
    before_tokens = estimate_tokens(body)

    # 上限：min(MAX_TOOL_CHARS, MAX_TOOL_ESTIMATED_TOKENS * CHARS_PER_TOKEN)
    hard_max_chars = min(
        settings.max_tool_chars,
        settings.max_tool_estimated_tokens * settings.chars_per_token,
    )

    if len(body) <= hard_max_chars:
        return BudgetResult(
            text=body,
            truncated=False,
            estimated_tokens=before_tokens,
            estimated_tokens_before=before_tokens,
            truncation_reason=None,
        )

    marker = f"\n{TOOL_RESULT_TRUNCATED}"
    keep = max(0, hard_max_chars - len(marker))
    new_body = body[:keep] + marker
    after_tokens = estimate_tokens(new_body)
    return BudgetResult(
        text=new_body,
        truncated=True,
        estimated_tokens=after_tokens,
        estimated_tokens_before=before_tokens,
        truncation_reason="tool_message_budget_exceeded",
    )
