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
              className="font-medium"
              style={{
                background:
                  "linear-gradient(90deg, #9ca3af 0%, #9ca3af 35%, #ffffff 50%, #9ca3af 65%, #9ca3af 100%)",
                backgroundSize: "200% 100%",
                WebkitBackgroundClip: "text",
                color: "transparent",
                animation: "thinkingShimmer 3.5s infinite linear",
              }}
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
          @keyframes thinkingShimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
          }
          /* Soft pulse on the trailing ellipsis so even if the shimmer
             is hard to see against the background, motion is obvious. */
          .thinking-dots {
            display: inline-block;
            animation: dotsPulse 1.8s ease-in-out infinite;
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
