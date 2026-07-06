"use client";

import type { ToolMessage as ToolMsg } from "@/lib/types";

// tool 独占一行：tool_name + purpose + preview(200)。完整结果仅后端/Mongo 保存，不给前端展开。
export default function ToolMessage({ msg }: { msg: ToolMsg }) {
  return (
    <div className="tool">
      <div className="tool-head">
        {msg.purpose && <span className="tool-purpose">{msg.purpose}</span>}
        {typeof msg.estimatedTokens === "number" && (
          <span className="tag">~{msg.estimatedTokens} tokens</span>
        )}
        {msg.truncated && (
          <span className="tag warn">
            已截断{msg.truncationReason ? `：${msg.truncationReason}` : ""}
          </span>
        )}
      </div>
      {msg.preview && (
        <div className="tool-preview">
          {msg.preview}
        </div>
      )}
    </div>
  );
}
