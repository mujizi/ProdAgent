"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat } from "@/lib/chatStream";
import { DEFAULT_SCRIPT_ID, DEFAULT_USER_ID, newSessionId } from "@/lib/session";
import type { ChatMessage } from "@/lib/types";
import ChatInput from "./ChatInput";
import MessageList from "./MessageList";

let seq = 0;
const uid = (p: string) => `${p}_${Date.now().toString(36)}_${seq++}`;

export default function ChatPage() {
  // session_id 仅在客户端挂载后生成，避免 SSR/客户端不一致导致 hydration mismatch
  const [sessionId, setSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  // 仅在用户发消息时 +1 触发滚到底；流式更新不自动吸底
  const [scrollSignal, setScrollSignal] = useState(0);

  useEffect(() => {
    if (!sessionId) setSessionId(newSessionId());
  }, [sessionId]);

  // 流式渲染节流：delta 累加到 ref，用 rAF 刷新当前 assistant 气泡（plan §7.4）
  const pendingRef = useRef("");
  const assistantIdRef = useRef<string | null>(null);
  const rafRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const flush = useCallback(() => {
    rafRef.current = null;
    const id = assistantIdRef.current;
    if (!id) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id && m.type === "assistant"
          ? { ...m, content: pendingRef.current }
          : m
      )
    );
  }, []);

  const scheduleFlush = useCallback(() => {
    if (rafRef.current != null) return;
    rafRef.current = requestAnimationFrame(flush);
  }, [flush]);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    pendingRef.current = "";
    assistantIdRef.current = null;
    setSessionId(newSessionId());
    setMessages([]);
    setError(null);
    setIsStreaming(false);
  }, []);

  const send = useCallback(
    async (question: string) => {
      const activeSessionId = sessionId || newSessionId();
      if (!sessionId) setSessionId(activeSessionId);
      setError(null);
      setIsStreaming(true);
      pendingRef.current = "";
      assistantIdRef.current = null;

      setMessages((prev) => [
        ...prev,
        { id: uid("u"), type: "user", content: question },
      ]);
      setScrollSignal((s) => s + 1);

      const abort = new AbortController();
      abortRef.current = abort;

      try {
        await streamChat(
          {
            userId: DEFAULT_USER_ID,
            sessionId: activeSessionId,
            scriptId: DEFAULT_SCRIPT_ID,
            question,
          },
          {
            onStatus: (msg) =>
              setMessages((prev) => [
                ...prev,
                { id: uid("s"), type: "status", content: msg, variant: "analyzing" },
              ]),
            onToolStart: (d) =>
              setMessages((prev) => {
                const withoutAnalyzing = prev.filter(
                  (m) => !(m.type === "status" && m.variant === "analyzing")
                );
                return [
                  ...withoutAnalyzing,
                  {
                    id: uid("s"),
                    type: "status",
                    content: `正在查询：${d.purpose || d.tool_name}`,
                    variant: "query",
                  },
                ];
              }),
            onToolResult: (d) =>
              setMessages((prev) => [
                ...prev,
                {
                  id: uid("t"),
                  type: "tool",
                  toolName: d.tool_name,
                  purpose: d.purpose,
                  preview: d.preview,
                  truncated: d.truncated,
                  estimatedTokens: d.estimated_tokens,
                  truncationReason: d.truncation_reason,
                  expandable: d.expandable,
                },
              ]),
            onDelta: (text) => {
              pendingRef.current += text;
              if (!assistantIdRef.current) {
                const id = uid("a");
                assistantIdRef.current = id;
                setMessages((prev) => {
                  const withoutAnalyzing = prev.filter(
                    (m) => !(m.type === "status" && m.variant === "analyzing")
                  );
                  return [
                    ...withoutAnalyzing,
                    { id, type: "assistant", content: "", streaming: true },
                  ];
                });
              }
              scheduleFlush();
            },
            onDone: () => {
              if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
              rafRef.current = null;
              const id = assistantIdRef.current;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id && m.type === "assistant"
                    ? { ...m, content: pendingRef.current, streaming: false }
                    : m
                )
              );
              assistantIdRef.current = null;
              setIsStreaming(false);
            },
            onError: (msg) => {
              setError(msg);
              setIsStreaming(false);
            },
          },
          abort.signal
        );
      } catch (e: any) {
        if (e?.name !== "AbortError") setError(String(e?.message || e));
        setIsStreaming(false);
      }
    },
    [sessionId, scheduleFlush]
  );

  return (
    <div className="app">
      <div className="header">
        <div>
          <h1>剧本问答助手</h1>
          <span className="sub">
            {sessionId ? `session: ${sessionId.slice(0, 14)}…` : "新会话"}
          </span>
        </div>
        <button className="new-chat-btn" onClick={newChat}>
          ＋ New Chat
        </button>
      </div>
      <MessageList messages={messages} error={error} scrollSignal={scrollSignal} />
      <ChatInput disabled={isStreaming} onSend={send} />
    </div>
  );
}
