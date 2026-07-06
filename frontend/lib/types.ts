// 前端消息类型（plan §7.3）

export type ChatMessage = UserMessage | AssistantMessage | ToolMessage | StatusMessage;

export type UserMessage = { id: string; type: "user"; content: string };

export type AssistantMessage = {
  id: string;
  type: "assistant";
  content: string;
  streaming?: boolean;
};

export type ToolMessage = {
  id: string;
  type: "tool";
  toolName: string;
  purpose: string;
  preview: string;
  truncated?: boolean;
  estimatedTokens?: number;
  truncationReason?: string | null;
  expandable?: boolean;
};

// variant: "analyzing" = 临时(闪一下即移除)；"query" = 正在查询(保留、突出)
export type StatusMessage = {
  id: string;
  type: "status";
  content: string;
  variant: "analyzing" | "query";
};
