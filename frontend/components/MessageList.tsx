"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import Markdown from "./Markdown";
import ToolMessage from "./ToolMessage";

export default function MessageList({
  messages,
  error,
  scrollSignal,
}: {
  messages: ChatMessage[];
  error: string | null;
  scrollSignal: number;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  // 仅在 scrollSignal 变化时滚到底（用户发消息时），流式/工具更新不自动吸底
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [scrollSignal]);

  return (
    <div className="messages">
      <div className="thread">
        {messages.length === 0 && !error && (
          <div className="empty">
            剧本问答助手
            <br />
            试试：第8场发生了什么？ / 这个剧本讲什么？ / 女主穿什么？
          </div>
        )}

        {messages.map((m) => {
          if (m.type === "user") {
            return (
              <div className="row user" key={m.id}>
                <div className="bubble user">{m.content}</div>
              </div>
            );
          }
          if (m.type === "assistant") {
            return (
              <div className="row assistant" key={m.id}>
                <div className="assistant-body">
                  <Markdown>{m.content}</Markdown>
                  {m.streaming && <span className="cursor">▋</span>}
                </div>
              </div>
            );
          }
          if (m.type === "tool") {
            return <ToolMessage msg={m} key={m.id} />;
          }
          if (m.type === "status") {
            const queryPrefix = "正在查询：";
            const isQuery = m.variant === "query" && m.content.startsWith(queryPrefix);
            const queryText = isQuery ? m.content.slice(queryPrefix.length) : m.content;

            return (
              <div className={`status ${m.variant}`} key={m.id}>
                {isQuery ? (
                  <>
                    <span className="status-label">{queryPrefix}</span>
                    <span className="status-text">{queryText}</span>
                  </>
                ) : (
                  m.content
                )}
              </div>
            );
          }
          return null;
        })}

        {error && <div className="error">⚠️ {error}</div>}
        <div ref={endRef} />
      </div>
    </div>
  );
}
