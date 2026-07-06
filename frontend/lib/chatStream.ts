// 直连后端 /api/chat/stream，解析 SSE（plan §6.1）。
// 用 fetch + ReadableStream（POST，EventSource 仅支持 GET）。
import { API_BASE } from "./session";

export type ToolStartData = {
  tool_call_id: string;
  tool_name: string;
  purpose: string;
};

export type ToolResultData = {
  tool_call_id: string;
  tool_name: string;
  purpose: string;
  preview: string;
  truncated: boolean;
  estimated_tokens: number;
  truncation_reason: string | null;
  expandable?: boolean;
};

export type StreamHandlers = {
  onStatus?: (msg: string) => void;
  onToolStart?: (d: ToolStartData) => void;
  onToolResult?: (d: ToolResultData) => void;
  onDelta?: (text: string) => void;
  onDone?: (sessionId: string) => void;
  onError?: (msg: string) => void;
};

export async function streamChat(
  params: { userId: string; sessionId: string; scriptId: string; question: string },
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: params.userId,
      session_id: params.sessionId,
      script_id: params.scriptId,
      question: params.question,
    }),
    signal,
  });

  if (!resp.ok || !resp.body) {
    handlers.onError?.(`请求失败：HTTP ${resp.status}`);
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (block: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
    }
    if (dataLines.length === 0) return;
    let data: any;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    switch (event) {
      case "status":
        handlers.onStatus?.(data.message);
        break;
      case "tool_start":
        handlers.onToolStart?.(data);
        break;
      case "tool_result":
        handlers.onToolResult?.(data);
        break;
      case "delta":
        handlers.onDelta?.(data.text);
        break;
      case "done":
        handlers.onDone?.(data.session_id);
        break;
      case "error":
        handlers.onError?.(data.message);
        break;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 事件以空行（\n\n）分隔
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (block.trim()) dispatch(block);
    }
  }
  if (buffer.trim()) dispatch(buffer);
}
