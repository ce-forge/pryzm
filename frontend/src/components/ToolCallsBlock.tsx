"use client";
/**
 * Renders the structured tool_calls list on an assistant turn.
 *
 * Visual style mirrors what users have seen in chat all along — a `> **Tool:**`
 * blockquote header followed by a `text` code block — but driven by structured
 * props instead of markdown embedded in the message content. Source of truth
 * lives in the assistant row's tool_calls JSONB column (or, mid-stream, in
 * useInference's streamingToolCalls slice).
 */
import type { ToolCall } from "@/types/chat";


function _formatArgs(args: Record<string, unknown>): string {
  const keys = Object.keys(args);
  if (keys.length === 0) return "";
  if (keys.length === 1) {
    const v = args[keys[0]];
    return `\`${JSON.stringify(v)}\``;
  }
  return keys.map((k) => `\`${k}=${JSON.stringify(args[k])}\``).join(", ");
}


export default function ToolCallsBlock({ calls }: { calls: ToolCall[] }) {
  if (!calls || calls.length === 0) return null;

  return (
    <div className="mt-2 flex flex-col gap-3 w-full">
      {calls.map((tc, i) => {
        const argsRendered = _formatArgs(tc.args);
        const header = argsRendered
          ? `> **Tool:** \`${tc.name}\` → ${argsRendered}`
          : `> **Tool:** \`${tc.name}\``;
        return (
          <div key={i} className="flex flex-col gap-1.5 w-full">
            <div className="text-[13px] text-gray-300 whitespace-pre-wrap">{header}</div>
            {tc.result ? (
              <pre className="rounded-lg bg-[#1e1f20] border border-[#333537] px-3 py-2 text-[12px] text-gray-200 whitespace-pre-wrap overflow-x-auto">
                {tc.result}
              </pre>
            ) : (
              <div className="text-[12px] text-gray-500 italic">running…</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
