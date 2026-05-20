"use client";
/**
 * Renders the structured tool_calls list on an assistant turn.
 *
 * Visual style mirrors AssistantMessage's blockquote renderer; the result
 * block uses `<pre>` for monospace display matching the inline `<code>`
 * styling elsewhere in the chat surface.
 */
import { useState } from "react";
import type { ToolCall } from "@/types/chat";
import { TerminalIcon } from "./Icons";


type WebSource = { n: number; title: string; url: string };
type WebFailure = { url: string; reason: string };

function parseWebSearchResult(result: string): { searchedAs: string | null; sources: WebSource[]; failures: WebFailure[] } {
  const searchedMatch = result.match(/^\*\*Searched as:\*\*\s*(.+?)$/m);
  const searchedAs = searchedMatch ? searchedMatch[1].trim() : null;

  const sources: WebSource[] = [];
  const sourceRe = /^### Source \[(\d+)\]:\s*(.+?)\n(\S+)/gm;
  let m: RegExpExecArray | null;
  while ((m = sourceRe.exec(result)) !== null) {
    sources.push({ n: parseInt(m[1], 10), title: m[2].trim(), url: m[3].trim() });
  }

  const failures: WebFailure[] = [];
  const footerMatch = result.match(/\*\*Failed sources\*\*\n([\s\S]+)$/);
  if (footerMatch) {
    const lines = footerMatch[1].split(/\n/);
    for (const line of lines) {
      const fm = line.match(/^-\s*(\S+)\s*—\s*(.+)$/);
      if (fm) failures.push({ url: fm[1], reason: fm[2].trim() });
    }
  }

  return { searchedAs, sources, failures };
}

function WebSearchResultPill({ result }: { result: string }) {
  const [expanded, setExpanded] = useState(false);
  const { searchedAs, sources, failures } = parseWebSearchResult(result);

  return (
    <div className="mt-4 mb-1">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="inline-flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-300 transition-colors cursor-pointer"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-3 h-3"
        >
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <span>
          {sources.length} source{sources.length === 1 ? "" : "s"}
          {failures.length > 0 ? ` (${failures.length} unreachable)` : ""}
        </span>
        <span className="text-gray-600">{expanded ? "▾" : "▸"}</span>
      </button>
      {expanded && (
        <div className="mt-2 rounded-md bg-[#161718] border border-[#2a2b2c] px-3 py-2.5 text-[12px] text-gray-300 flex flex-col gap-2 max-w-2xl">
          {searchedAs && (
            <div className="pb-2 border-b border-[#2a2b2c] text-[10.5px] text-gray-500">
              <span className="text-gray-600">searched: </span>
              <span className="font-mono text-gray-400">{searchedAs}</span>
            </div>
          )}
          {sources.map((s) => (
            <div key={s.n} className="flex flex-col gap-0.5">
              <div className="text-gray-300 text-[12px] leading-snug">
                <span className="text-gray-500 font-mono text-[11px]">[{s.n}]</span>{" "}
                {s.title}
              </div>
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400/80 hover:text-blue-300 hover:underline break-all font-mono text-[10.5px]"
              >
                {s.url}
              </a>
            </div>
          ))}
          {failures.length > 0 && (
            <div className="mt-1 pt-2 border-t border-[#2a2b2c]">
              <div className="text-[10.5px] text-gray-600 mb-1">unreachable:</div>
              {failures.map((f, i) => (
                <div key={i} className="text-[10.5px] text-gray-600 font-mono break-all">
                  {f.url} <span className="text-gray-700">— {f.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function ArgPills({ args }: { args: Record<string, unknown> }) {
  const keys = Object.keys(args);
  if (keys.length === 0) return null;

  // 1 arg → render bare value; multi-arg → render key="value" pairs
  if (keys.length === 1) {
    const v = args[keys[0]];
    return (
      <>
        {" → "}
        <code className="bg-[#2a2b2c] px-1.5 py-0.5 rounded text-[12px] font-mono">
          {JSON.stringify(v)}
        </code>
      </>
    );
  }

  return (
    <>
      {" → "}
      {keys.map((k, i) => (
        <span key={k}>
          <code className="bg-[#2a2b2c] px-1.5 py-0.5 rounded text-[12px] font-mono">
            {`${k}=${JSON.stringify(args[k])}`}
          </code>
          {i < keys.length - 1 ? ", " : ""}
        </span>
      ))}
    </>
  );
}


export default function ToolCallsBlock({
  calls,
  isStreaming = false,
}: {
  calls: ToolCall[];
  isStreaming?: boolean;
}) {
  if (!calls || calls.length === 0) return null;

  return (
    <div className="w-full flex flex-col gap-3">
      {calls.map((tc, i) => {
        // web_search renders as a self-contained pill (with a "searched: ..."
        // header inside the expansion) — no separate "Tool: web_search → ..."
        // blockquote, since it's redundant noise. The pill is also hidden
        // until streaming completes — during the stream it competes with the
        // prose for attention; once the reply is done it sits quietly under
        // the message as an attribution affordance.
        if (tc.name === "web_search") {
          if (isStreaming || !tc.result) return null;
          return (
            <div key={i} className="w-full">
              <WebSearchResultPill result={tc.result} />
            </div>
          );
        }
        return (
          <div key={i} className="w-full">
            <blockquote className="bg-[#1a1b1c] border border-[#333537] border-l-4 border-l-blue-500 text-gray-300 px-4 py-3 rounded-r-lg my-2 flex items-start gap-3">
              <TerminalIcon />
              <div className="flex-1 text-[13px] break-words min-w-0">
                <strong>Tool:</strong>{" "}
                <code className="bg-[#2a2b2c] px-1.5 py-0.5 rounded text-[12px] font-mono">
                  {tc.name}
                </code>
                <ArgPills args={tc.args} />
              </div>
            </blockquote>
            {tc.result ? (
              <pre className="rounded-lg bg-[#1e1f20] border border-[#333537] px-3 py-2 text-[12px] text-gray-200 whitespace-pre-wrap overflow-x-auto -mt-1 mb-2">
                {tc.result}
              </pre>
            ) : (
              <div className="text-[12px] text-gray-500 italic px-3 -mt-1 mb-2">running…</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
