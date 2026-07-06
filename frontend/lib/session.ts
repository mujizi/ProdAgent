// session_id 生成（plan §7.2 New Chat）

export function newSessionId(): string {
  const rnd = Math.random().toString(16).slice(2, 10);
  return `sess_${Date.now().toString(16)}${rnd}`;
}

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

// 默认剧本：肖申克的救赎（后端真实数据，三表齐全）
export const DEFAULT_SCRIPT_ID =
  process.env.NEXT_PUBLIC_SCRIPT_ID || "690c1b6736c9c50c40160976";

export const DEFAULT_USER_ID =
  process.env.NEXT_PUBLIC_USER_ID || "dev_user_frontend";
