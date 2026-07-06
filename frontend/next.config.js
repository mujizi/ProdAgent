/** @type {import('next').NextConfig} */
// 前端直连后端 8000（plan §0：不经 Next.js 转发，避免缓冲破坏 SSE）。
// 后端地址通过 NEXT_PUBLIC_API_BASE 注入，默认 http://localhost:8000。
const nextConfig = {
  reactStrictMode: true,
};

module.exports = nextConfig;
