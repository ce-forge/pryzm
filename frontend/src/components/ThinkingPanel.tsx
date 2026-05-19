"use client";

import React, { useState } from "react";
import PrismIndicator from "./PrismIndicator";

interface ThinkingPanelProps {
  /** Reasoning_content accumulated so far. Empty/null is valid while a
   *  reasoning turn is mid-stream — the pill still renders. */
  reasoning: string | null | undefined;
  /**
   * Wall-clock duration of the reasoning phase, in seconds. Two sources:
   *   - During streaming: the per-session value useInference captures
   *     from the `reasoning_done` SSE event (lands BEFORE content begins).
   *   - After persistence: the value on the message row.
   * Either way, presence of a duration is the signal that thinking has
   * finished — the pill flips from `Thinking…` + prism to `Thought for
   * X.Xs` without prism, even while content keeps streaming.
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

  // Render conditions:
  //   - There's reasoning text to surface (live or frozen), OR
  //   - This is the pre-thinking moment of a reasoning turn (no text yet
  //     but the caller decided to show a pill).
  if (!reasoning && !isStreaming) return null;

  // The duration's existence — not the global isStreaming flag — is what
  // flips the pill from active to done. reasoning_done fires the moment
  // </think> lands, well before the rest of the response finishes.
  const isThinking = durationSeconds == null;
  const labelText = isThinking ? "Thinking" : `Thought for ${durationSeconds}s`;

  return (
    <div className="mt-1 mb-2 max-w-3xl">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={[
          "group inline-flex items-center gap-2 px-3 py-1.5",
          "rounded-lg border border-[#2a2a2c] bg-[#161617]/70",
          "hover:bg-[#1c1c1d] hover:border-[#3a3a3c]",
          "text-[13px] tracking-wide text-gray-300 transition-colors",
        ].join(" ")}
        aria-expanded={open}
      >
        <span
          className={[
            "inline-block text-gray-500 transition-transform duration-150",
            open ? "rotate-90" : "",
          ].join(" ")}
        >
          ▸
        </span>
        {isThinking ? (
          <>
            <span
              className="font-medium thinking-shimmer"
            >
              {labelText}
              <span className="thinking-dots">…</span>
            </span>
            <PrismIndicator size="pill" />
          </>
        ) : (
          <span className="font-medium text-gray-300">{labelText}</span>
        )}
        <style>{`
          /* Prismatic shimmer — the highlight passing across the text
             splits into pink-white-blue (chromatic aberration / dispersion),
             tying back to the prism's rainbow theme. Smooth 2.8s cycle. */
          .thinking-shimmer {
            background-image: linear-gradient(
              90deg,
              rgba(156, 163, 175, 1) 0%,
              rgba(156, 163, 175, 1) 38%,
              rgba(244, 114, 182, 0.85) 46%,
              rgba(255, 255, 255, 1) 50%,
              rgba(96, 165, 250, 0.85) 54%,
              rgba(156, 163, 175, 1) 62%,
              rgba(156, 163, 175, 1) 100%
            );
            background-size: 220% 100%;
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            animation: thinkingShimmer 2.8s infinite linear;
          }
          @keyframes thinkingShimmer {
            0% { background-position: 220% 0; }
            100% { background-position: -120% 0; }
          }
          /* Soft pulse on the trailing ellipsis so motion is obvious
             even if the shimmer isn't catching on a particular monitor. */
          .thinking-dots {
            display: inline-block;
            animation: dotsPulse 1.6s ease-in-out infinite;
          }
          @keyframes dotsPulse {
            0%, 100% { opacity: 0.4; }
            50% { opacity: 1; }
          }
        `}</style>
      </button>
      {open && (
        <div
          className={[
            "mt-2 px-3 py-2 rounded-lg border border-[#2a2a2c]",
            "bg-[#161617]/70 text-[12px] text-gray-400 leading-relaxed",
            "whitespace-pre-wrap",
          ].join(" ")}
        >
          {reasoning || (isThinking ? "…" : "")}
        </div>
      )}
    </div>
  );
}
