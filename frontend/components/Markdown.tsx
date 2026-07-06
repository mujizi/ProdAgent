"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

declare global {
  interface Window {
    mermaid?: any;
    __mermaidLoading?: Promise<void>;
  }
}

function loadMermaid() {
  if (window.mermaid) return Promise.resolve();
  if (window.__mermaidLoading) return window.__mermaidLoading;

  window.__mermaidLoading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/vendor/mermaid.min.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Mermaid 脚本加载失败"));
    document.head.appendChild(script);
  });

  return window.__mermaidLoading;
}

function normalizeMermaid(source: string) {
  return source
    .trim()
    .replace(/&lt;br\s*\/?&gt;/gi, "<br>")
    .replace(/<br\s*\/?>/gi, "<br>");
}

function looksLikeMermaid(source: string, className?: string) {
  const lang = /language-(\w+)/.exec(className || "")?.[1];
  const firstLine = source.trim().split(/\n/, 1)[0]?.trim() || "";
  return (
    lang === "mermaid" ||
    /^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|timeline|mindmap|gitGraph)\b/.test(
      firstLine
    )
  );
}

function MermaidDiagram({ chart }: { chart: string }) {
  const [svg, setSvg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const normalizedChart = useMemo(() => normalizeMermaid(chart), [chart]);
  const id = useMemo(
    () => `mermaid-${Math.random().toString(36).slice(2)}`,
    []
  );
  const stageRef = useRef<HTMLDivElement | null>(null);

  // 全屏时强制 SVG 撑满：去掉 mermaid 生成的固定 width/height，
  // 保证有 viewBox 以便等比缩放，并按视口放大。
  useEffect(() => {
    if (!fullscreen) return;
    const stage = stageRef.current;
    if (!stage) return;
    const svg = stage.querySelector("svg");
    if (!svg) return;

    const ensureViewBox = () => {
      const w = svg.getAttribute("width");
      const h = svg.getAttribute("height");
      const vb = svg.getAttribute("viewBox");
      if ((!vb || vb === "0 0 0 0") && w && h) {
        const wf = parseFloat(w);
        const hf = parseFloat(h);
        if (wf > 0 && hf > 0) {
          svg.setAttribute("viewBox", `0 0 ${wf} ${hf}`);
        }
      }
    };
    ensureViewBox();

    svg.removeAttribute("style");
    svg.style.maxWidth = "100%";
    svg.style.maxHeight = "100%";
    svg.style.width = "auto";
    svg.style.height = "auto";
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }, [fullscreen, svg]);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        await loadMermaid();
        const mermaid = window.mermaid;
        if (!mermaid) throw new Error("Mermaid 未初始化");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "base",
          flowchart: {
            htmlLabels: true,
          },
          themeVariables: {
            fontFamily:
              '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
            primaryColor: "#eff6ff",
            primaryTextColor: "#1f2937",
            primaryBorderColor: "#93c5fd",
            lineColor: "#64748b",
            secondaryColor: "#f8fafc",
            tertiaryColor: "#ffffff",
          },
        });
        const parsed = await mermaid.parse(normalizedChart, {
          suppressErrors: true,
        });
        if (parsed === false) {
          throw new Error("Mermaid 语法不兼容");
        }
        const { svg: rendered } = await mermaid.render(id, normalizedChart);
        if (!cancelled) {
          setSvg(rendered);
          setError(null);
        }
      } catch (e: any) {
        if (!cancelled) {
          setSvg("");
          setError(e?.message || "图表渲染失败");
        }
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [normalizedChart, id]);

  // 全屏时按 Esc 退出
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [fullscreen]);

  if (error) {
    return (
      <div className="mermaid-error">
        <div>图表渲染失败，已保留源码。</div>
        <pre>
          <code>{chart}</code>
        </pre>
      </div>
    );
  }

  return (
    <div className="mermaid-wrap">
      <div
        className="mermaid-box"
        dangerouslySetInnerHTML={{ __html: svg || "" }}
      />
      {svg && (
        <button
          type="button"
          className="mermaid-fullscreen-btn"
          onClick={() => setFullscreen(true)}
          aria-label="全屏查看"
          title="全屏查看"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3" />
            <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
            <path d="M3 16v3a2 2 0 0 0 2 2h3" />
            <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
          </svg>
        </button>
      )}

      {fullscreen && (
        <div
          className="mermaid-overlay"
          onClick={() => setFullscreen(false)}
          role="dialog"
          aria-modal="true"
        >
          <button
            type="button"
            className="mermaid-close-btn"
            onClick={() => setFullscreen(false)}
            aria-label="退出全屏"
            title="退出全屏 (Esc)"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
          <div
            ref={stageRef}
            className="mermaid-overlay-stage"
            onClick={(e) => e.stopPropagation()}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      )}
    </div>
  );
}

// 助手消息默认 Markdown 渲染（支持 GFM：表格/删除线/任务列表等）
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
          pre: ({ children }: any) => {
            const child = Array.isArray(children) ? children[0] : children;
            const className = child?.props?.className;
            const source = String(child?.props?.children || "").replace(/\n$/, "");
            if (looksLikeMermaid(source, className)) {
              return <MermaidDiagram chart={source} />;
            }
            return <pre>{children}</pre>;
          },
          code: ({ inline, node, className, children, ...props }: any) => {
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
