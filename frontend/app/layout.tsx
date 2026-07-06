import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "剧本问答助手",
  description: "ProdAgent 剧本问答 MVP",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
