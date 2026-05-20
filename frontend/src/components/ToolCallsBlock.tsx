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
    <div className="-mt-1 mb-2">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="text-[12px] text-gray-300 bg-[#1e1f20] border border-[#333537] rounded-lg px-3 py-1.5 hover:bg-[#252627] transition-colors cursor-pointer"
      >
        🌐 Searched: {sources.length} source{sources.length === 1 ? "" : "s"}
        {failures.length > 0 ? ` (${failures.length} failed)` : ""}
        {expanded ? " ▼" : " ▶"}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg bg-[#1e1f20] border border-[#333537] px-3 py-2 text-[12px] text-gray-200 flex flex-col gap-1.5">
          {searchedAs && (
            <div className="pb-2 mb-1 border-b border-[#333537] text-[11px] text-gray-400">
              Searched as:{" "}
              <span className="text-gray-200 font-mono">{searchedAs}</span>
            </div>
          )}
          {sources.map((s) => (
            <div key={s.n} className="flex flex-col">
              <div className="text-gray-300">
                <span className="text-gray-500 font-mono">[{s.n}]</span>{" "}
                <span>{s.title}</span>
              </div>
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 hover:text-blue-300 hover:underline break-all font-mono text-[11px]"
              >
                {s.url}
              </a>
            </div>
          ))}
          {failures.length > 0 && (
            <div className="mt-2 pt-2 border-t border-[#333537]">
              <div className="text-[11px] text-gray-500 mb-1">Failed to fetch:</div>
              {failures.map((f, i) => (
                <div key={i} className="text-[11px] text-gray-500 font-mono break-all">
                  {f.url} — {f.reason}
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


export default function ToolCallsBlock({ calls }: { calls: ToolCall[] }) {
  if (!calls || calls.length === 0) return null;

  return (
    <div className="w-full flex flex-col gap-3">
      {calls.map((tc, i) => {
        // web_search renders as a self-contained pill (with a "Searched as:"
        // header inside the expansion) — no separate "Tool: web_search → ..."
        // blockquote, since it's redundant noise.
        if (tc.name === "web_search") {
          return (
            <div key={i} className="w-full">
              {tc.result ? (
                <WebSearchResultPill result={tc.result} />
              ) : (
                <div className="text-[12px] text-gray-500 italic">🌐 searching the web…</div>
              )}
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
