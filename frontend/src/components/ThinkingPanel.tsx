"use client";

import React, { useState } from "react";
import PrismIndicator from "./PrismIndicator";

interface ThinkingPanelProps {
  /** Reasoning_content accumulated so far. Empty/null is valid during the
   *  pre-thinking phase of a reasoning turn — the pill still renders. */
  reasoning: string | null | undefined;
  /**
   * Wall-clock duration of the reasoning phase, in seconds. Shown in the
   * label once the stream has ended (`Thinking (1.6s)`). Ignored while
   * streaming — the label reads `Thinking…` with a live shimmer instead.
   */
  durationSeconds?: number | null;
  /**
   * True while the assistant turn is still streaming. Switches the label
   * to a shimmering `Thinking…` (acting as the live indicator instead of
   * the prism+phrase block) and renders the expanded panel even when
   * reasoning content hasn't started arriving yet.
   */
  isStreaming?: boolean;
}

export default function ThinkingPanel({
  reasoning,
  durationSeconds,
  isStreaming = false,
}: ThinkingPanelProps) {
  const [open, setOpen] = useState(false);

  // The pill is the single indicator for reasoning turns. While streaming
  // it shows up before any reasoning_content arrives — the caller has
  // already decided this is a reasoning turn (catalog tag), so an empty
  // pill at frame 1 is correct UX (matches Claude/Gemini's pattern).
  if (!isStreaming && !reasoning) return null;

  const showDuration = !isStreaming && durationSeconds != null;
  const labelText = showDuration ? `Thinking (${durationSeconds}s)` : "Thinking…";

  return (
    <div className="mt-1 mb-2 pl-1">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 text-[13px] text-gray-400 hover:text-gray-200 transition-colors"
      >
        <span className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
        {isStreaming ? (
          <>
            <span
              style={{
                background: "linear-gradient(90deg, #9ca3af 0%, #9ca3af 40%, #ffffff 50%, #9ca3af 60%, #9ca3af 100%)",
                backgroundSize: "200% 100%",
                WebkitBackgroundClip: "text",
                color: "transparent",
                animation: "thinkingShimmer 5s infinite linear",
              }}
            >
              {labelText}
            </span>
            <PrismIndicator />
          </>
        ) : (
          <span>{labelText}</span>
        )}
        <style>{`
          @keyframes thinkingShimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
          }
        `}</style>
      </button>
      {open && (
        <div className="mt-2 px-3 py-2 rounded-lg border border-[#333537] bg-[#1a1b1c] text-[12px] text-gray-400 leading-relaxed whitespace-pre-wrap">
          {reasoning || (isStreaming ? "…" : "")}
        </div>
      )}
    </div>
  );
}
