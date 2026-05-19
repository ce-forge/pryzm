"use client";

import React, { useState } from "react";

interface ThinkingPanelProps {
  /** Reasoning_content text. Empty/null renders nothing. */
  reasoning: string | null | undefined;
  /**
   * Wall-clock duration of the reasoning phase, in seconds. Shown next to
   * the disclosure label on the finished variant. Live variant ignores it.
   */
  durationSeconds?: number | null;
  /**
   * `live` sits beside the running ProcessingAnimation pill while the
   * model is still reasoning. `finished` sits above the assistant message
   * once persistence completes. Both default to collapsed.
   */
  variant?: "live" | "finished";
}

export default function ThinkingPanel({
  reasoning,
  durationSeconds,
  variant = "finished",
}: ThinkingPanelProps) {
  const [open, setOpen] = useState(false);

  if (!reasoning) return null;

  const showDuration = variant === "finished" && durationSeconds != null;

  return (
    <div className={variant === "live" ? "mt-2 pl-4" : "mt-1 mb-2 pl-1"}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
      >
        <span className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
        <span>Thinking{showDuration ? ` (${durationSeconds}s)` : ""}</span>
      </button>
      {open && (
        <div className="mt-2 px-3 py-2 rounded-lg border border-[#333537] bg-[#1a1b1c] text-[12px] text-gray-400 leading-relaxed whitespace-pre-wrap">
          {reasoning}
        </div>
      )}
    </div>
  );
}
