"use client";

import React from "react";

interface PrismIndicatorProps {
  /** `pill` is the 14px mark used inside ThinkingPanel; `block` is the
   *  20px mark used in the standalone ProcessingAnimation. */
  size?: "pill" | "block";
}

/**
 * Minimal prism mark. A single static triangle with a soft vertical
 * gradient fill — light at the top, sapphire haze through the middle,
 * fading to near-nothing at the base. One barely-perceptible 4s opacity
 * breathe is the only motion.
 *
 * Deliberately not a moving showcase. The prism is the brand mark, the
 * "alive" signal is the text shimmer next to it. Lighthouse beam,
 * spinning rays, halo glow — all removed in favour of restraint.
 */
export default function PrismIndicator({ size = "pill" }: PrismIndicatorProps) {
  const dim = size === "pill" ? 14 : 20;

  return (
    <svg
      width={dim}
      height={dim}
      viewBox="0 0 20 20"
      fill="none"
      className="shrink-0 prism-mark"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="prism-fill" x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.55)" />
          <stop offset="55%" stopColor="rgba(168,180,250,0.18)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0.04)" />
        </linearGradient>
      </defs>
      <style>{`
        .prism-mark { animation: prismMarkBreathe 4s ease-in-out infinite; }
        @keyframes prismMarkBreathe {
          0%, 100% { opacity: 0.72; }
          50% { opacity: 1; }
        }
      `}</style>
      <polygon
        points="10,2.5 17,16.5 3,16.5"
        fill="url(#prism-fill)"
        stroke="rgba(229, 231, 235, 0.55)"
        strokeWidth="1"
        strokeLinejoin="round"
      />
    </svg>
  );
}
