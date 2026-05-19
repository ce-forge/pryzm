"use client";

import React, { useState } from "react";
import ThinkingPanel from "@/components/ThinkingPanel";
import ProcessingAnimation from "@/components/ProcessingAnimation";
import PrismIndicator from "@/components/PrismIndicator";

const SAMPLE_REASONING = `The user is asking about Python list comprehensions vs map().

Plan:
1. Compare readability — list comprehensions are usually more Pythonic.
2. Compare performance — both are similar, generator expressions can be lazier.
3. Provide a small concrete example showing both.
4. Recommend list comprehensions for clarity, map() only when reusing a callable.

Let me write a brief, focused answer.`;

/**
 * Live prototyping page for the streaming-state pill + prism animation.
 * Renders every visual state side-by-side so we can iterate on the
 * design without round-tripping through a real chat turn. URL-accessible
 * at /admin/preview-pills; not listed in the admin tab nav.
 */
export default function PreviewPillsPage() {
  const [reasoning, setReasoning] = useState(SAMPLE_REASONING);
  const [duration, setDuration] = useState<number>(1.6);
  const [reset, setReset] = useState(0);

  const remount = () => setReset((r) => r + 1);

  return (
    <div className="p-8 space-y-8 text-gray-300" key={reset}>
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold">Pill preview lab</h1>
          <p className="text-sm text-gray-500 mt-1">
            URL-accessible only. Iterate on the live-thinking pill and prism animation here.
          </p>
        </div>
        <button
          onClick={remount}
          className="text-xs px-3 py-1.5 rounded-lg border border-[#333] hover:border-[#555]"
        >
          ↻ Re-mount (replays animations)
        </button>
      </header>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Controls</h2>
        <div className="flex items-center gap-4">
          <label className="text-xs flex items-center gap-2">
            Duration (s):
            <input
              type="number"
              value={duration}
              onChange={(e) => setDuration(parseFloat(e.target.value) || 0)}
              step="0.1"
              className="w-20 bg-[#0e0e0f] border border-[#333] rounded px-2 py-1 text-sm"
            />
          </label>
        </div>
        <label className="text-xs flex flex-col gap-1">
          Reasoning content:
          <textarea
            value={reasoning}
            onChange={(e) => setReasoning(e.target.value)}
            rows={6}
            className="w-full bg-[#0e0e0f] border border-[#333] rounded px-2 py-1 text-sm font-mono"
          />
        </label>
      </section>

      <section className="space-y-4 border-t border-[#2a2a2c] pt-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          ThinkingPanel — active (no duration yet)
        </h2>
        <p className="text-xs text-gray-500">
          What the user sees while the model is still in &lt;think&gt;…&lt;/think&gt;. Pill expandable to live reasoning.
        </p>
        <ThinkingPanel reasoning={reasoning} durationSeconds={null} isStreaming={true} />
      </section>

      <section className="space-y-4 border-t border-[#2a2a2c] pt-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          ThinkingPanel — pre-thinking (empty, still streaming)
        </h2>
        <p className="text-xs text-gray-500">
          First ~100 ms after the user sends — pill exists, no reasoning text yet.
        </p>
        <ThinkingPanel reasoning="" durationSeconds={null} isStreaming={true} />
      </section>

      <section className="space-y-4 border-t border-[#2a2a2c] pt-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          ThinkingPanel — done (mid-content stream)
        </h2>
        <p className="text-xs text-gray-500">
          The moment reasoning_done lands. No prism. Click to re-read the trace.
        </p>
        <ThinkingPanel reasoning={reasoning} durationSeconds={duration} isStreaming={true} />
      </section>

      <section className="space-y-4 border-t border-[#2a2a2c] pt-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          ThinkingPanel — finished (persisted, post-stream)
        </h2>
        <p className="text-xs text-gray-500">
          Same as above but the turn has fully completed. No semantic difference visually.
        </p>
        <ThinkingPanel reasoning={reasoning} durationSeconds={duration} isStreaming={false} />
      </section>

      <section className="space-y-4 border-t border-[#2a2a2c] pt-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          ProcessingAnimation — non-reasoning turn
        </h2>
        <p className="text-xs text-gray-500">
          Small-model turns. Themed phrase + the larger 80x40 prism.
        </p>
        <ProcessingAnimation />
      </section>

      <section className="space-y-4 border-t border-[#2a2a2c] pt-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          PrismIndicator — sizes, side by side
        </h2>
        <p className="text-xs text-gray-500">Pill (56×28) vs Block (80×40). Same animation set.</p>
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-16">pill</span>
            <PrismIndicator size="pill" />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-16">block</span>
            <PrismIndicator size="block" />
          </div>
        </div>
      </section>

      <section className="space-y-4 border-t border-[#2a2a2c] pt-6">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Contrast tests
        </h2>
        <p className="text-xs text-gray-500">Verify the pill reads on different backgrounds.</p>
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 rounded bg-[#0a0a0b]">
            <p className="text-xs mb-2 text-gray-500">on #0a0a0b (deeper)</p>
            <ThinkingPanel reasoning={reasoning} durationSeconds={null} isStreaming={true} />
          </div>
          <div className="p-4 rounded bg-[#1f1f20]">
            <p className="text-xs mb-2 text-gray-500">on #1f1f20 (lighter)</p>
            <ThinkingPanel reasoning={reasoning} durationSeconds={null} isStreaming={true} />
          </div>
        </div>
      </section>
    </div>
  );
}
