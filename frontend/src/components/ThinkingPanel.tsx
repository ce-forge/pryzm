"use client";

import React, { useState } from "react";
import PrismIndicator from "./PrismIndicator";

interface ThinkingPanelProps {
  /** Reasoning_content accumulated so far. Empty/null is valid while a
   *  reasoning turn is mid-stream — the pill still renders. */
  reasoning: string | null | undefined;
  /**
   * Wall-clock duration of the reasoning phase, in seconds. Sources:
   *   - Live: useInference's streamingReasoningDurationS, set the moment
   *     the backend's `reasoning_done` SSE event lands (before content).
   *   - Persisted: the message row.
   * Presence of a duration flips the pill from `Thinking` to
   * `Thought for X.Xs` — the global stream-finished flag isn't enough.
   */
  durationSeconds?: number | null;
  /** True while the assistant turn is still streaming; combined with
   *  empty reasoning, used to render the pre-thinking pill. */
  isStreaming?: boolean;
}

export default function ThinkingPanel({
  reasoning,
  durationSeconds,
  isStreaming = false,
}: ThinkingPanelProps) {
  const [open, setOpen] = useState(false);

  // Render conditions: existing reasoning text (live or frozen), OR a
  // streaming reasoning turn whose thinking hasn't started yet.
  if (!reasoning && !isStreaming) return null;

  // Duration's existence flips the visual — not the global isStreaming
  // flag. reasoning_done fires the instant </think> lands, before any
  // content streams, and the pill should respect that boundary.
  const isThinking = durationSeconds == null;
  const labelText = isThinking ? "Thinking" : `Thought for ${durationSeconds}s`;

  return (
    <div className="mt-1 mb-2 max-w-3xl">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={[
          "group inline-flex items-center gap-2 px-2.5 py-1",
          "rounded-md border border-[#2a2a2c] bg-[#161617]/50",
          "hover:border-[#3f3f42] hover:bg-[#1c1c1d]",
          "text-[12px] tracking-[0.01em] text-gray-400 hover:text-gray-200",
          "transition-colors",
        ].join(" ")}
        aria-expanded={open}
      >
        <span
          className={[
            "inline-block text-[10px] leading-none text-gray-500 transition-transform duration-150",
            open ? "rotate-90" : "",
          ].join(" ")}
        >
          ›
        </span>
        {isThinking ? (
          <>
            <PrismIndicator size="pill" />
            <span className="font-medium thinking-shimmer">{labelText}</span>
          </>
        ) : (
          <>
            <PrismIndicator size="pill" />
            <span className="font-medium">{labelText}</span>
          </>
        )}
        <style>{`
          /* Soft shimmer — single white highlight band slides through a
             grey field. No chromatic split, no fast cycle. 3.2s feels
             considered. The prism mark's breathe carries the rest of
             the 'alive' signal. */
          .thinking-shimmer {
            background-image: linear-gradient(
              90deg,
              rgba(156, 163, 175, 1) 0%,
              rgba(156, 163, 175, 1) 44%,
              rgba(243, 244, 246, 1) 50%,
              rgba(156, 163, 175, 1) 56%,
              rgba(156, 163, 175, 1) 100%
            );
            background-size: 240% 100%;
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            animation: shimmerSweep 3.2s linear infinite;
          }
          @keyframes shimmerSweep {
            0% { background-position: 240% 0; }
            100% { background-position: -140% 0; }
          }
        `}</style>
      </button>
      {open && (
        <div
          className={[
            "mt-2 px-3 py-2 rounded-md border border-[#2a2a2c]",
            "bg-[#161617]/50 text-[12px] text-gray-400 leading-relaxed",
            "whitespace-pre-wrap",
          ].join(" ")}
        >
          {reasoning || (isThinking ? "…" : "")}
        </div>
      )}
    </div>
  );
}
