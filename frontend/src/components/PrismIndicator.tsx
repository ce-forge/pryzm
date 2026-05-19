"use client";

import React from "react";

interface PrismIndicatorProps {
  /** Visual sizing. `pill` is the compact 56x28 used inside ThinkingPanel;
   *  `block` is the larger 80x40 used in the standalone ProcessingAnimation. */
  size?: "pill" | "block";
}

/**
 * Animated prism + lighthouse beam, the single live-activity indicator
 * across the chat surface. Used inside ThinkingPanel (reasoning turns)
 * and ProcessingAnimation (non-reasoning turns).
 *
 * Layered animations on independent clocks so something is always
 * happening:
 *   - prismSpin / shootWhite / shootColor / flareAnim (5s) — the main
 *     lighthouse cycle. White beam in from left, white→rainbow burst,
 *     prism snaps through 120°.
 *   - prismFloat / prismBreathe / haloPulse (3.4s) — float + stroke
 *     pulse + halo glow on a slightly off-tempo clock so the prism
 *     reads as a suspended, living object even between beam events.
 *   - raysSweep (5s, in sync with shootColor) — small angular sweep
 *     on the rainbow rays so they pan as they exit, lighthouse-style.
 */
export default function PrismIndicator({ size = "pill" }: PrismIndicatorProps) {
  const dims = size === "pill" ? "w-14 h-7" : "w-20 h-10";

  return (
    <svg
      viewBox="0 0 60 30"
      className={`${dims} overflow-visible shrink-0 prism-svg`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <filter id="prism-glow" filterUnits="userSpaceOnUse" x="-10" y="-10" width="80" height="50">
          <feGaussianBlur stdDeviation="1" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        {/* Soft halo behind the prism — radial gradient white→transparent
            so the centre glows and fades out smoothly to nothing. */}
        <radialGradient id="prism-halo" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.35)" />
          <stop offset="55%" stopColor="rgba(168,180,250,0.12)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0)" />
        </radialGradient>
      </defs>

      <style>
        {`
          /* Float on the whole SVG. Off-tempo from the 5s beam cycle so
             nothing locks into a repetitive looking rhythm. */
          .prism-svg { animation: prismFloat 3.4s ease-in-out infinite; }

          .halo { transform-origin: 20px 17px; animation: haloPulse 3.4s ease-in-out infinite; }
          .rays { transform-origin: 20px 17px; animation: raysSweep 5s infinite cubic-bezier(0.2, 1, 0.3, 1); }
          .beam-white { stroke-dasharray: 12 50; animation: shootWhite 5s infinite linear; }
          .beam-color { stroke-dasharray: 10 50; animation: shootColor 5s infinite cubic-bezier(0.2, 1, 0.3, 1); }
          .flare { transform-origin: 20px 17px; animation: flareAnim 5s infinite ease-out; }
          .prism-glass {
            transform-origin: 20px 17px;
            animation: prismSpin 5s infinite cubic-bezier(0.34, 1.56, 0.64, 1),
                       prismBreathe 3.4s ease-in-out infinite;
          }

          @keyframes prismFloat {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-3px); }
          }

          @keyframes prismBreathe {
            0%, 100% { stroke-opacity: 0.45; }
            50% { stroke-opacity: 1.0; }
          }

          /* Halo grows + brightens with the breathe — the prism appears
             to inhale and exhale light. */
          @keyframes haloPulse {
            0%, 100% { transform: scale(0.85); opacity: 0.35; }
            50% { transform: scale(1.15); opacity: 0.95; }
          }

          @keyframes raysSweep {
            0%, 59.9% { transform: rotate(0deg); }
            60% { transform: rotate(-4deg); }
            70% { transform: rotate(4deg); }
            72%, 100% { transform: rotate(0deg); }
          }

          @keyframes shootWhite {
            0%, 50% { stroke-dashoffset: 12; opacity: 0; }
            51% { stroke-dashoffset: 9; opacity: 1; }
            60% { stroke-dashoffset: -8; opacity: 1; }
            60.1%, 100% { stroke-dashoffset: -8; opacity: 0; }
          }

          @keyframes shootColor {
            0%, 59.9% { stroke-dashoffset: 10; opacity: 0; }
            60% { stroke-dashoffset: 10; opacity: 1; }
            70% { stroke-dashoffset: -37; opacity: 1; }
            72%, 100% { stroke-dashoffset: -37; opacity: 0; }
          }

          @keyframes flareAnim {
            0%, 59.9% { transform: scale(0); opacity: 0; }
            60% { transform: scale(1.5); opacity: 1; }
            65%, 100% { transform: scale(0); opacity: 0; }
          }

          @keyframes prismSpin {
            0%, 59.9% { transform: rotate(0deg); fill: rgba(255,255,255,0); stroke: #4b5563; }
            60% { fill: rgba(255,255,255,0.4); stroke: #ffffff; transform: rotate(0deg); }
            65% { fill: rgba(255,255,255,0.1); stroke: #9ca3af; transform: rotate(30deg); }
            75%, 100% { transform: rotate(120deg); fill: rgba(255,255,255,0); stroke: #4b5563; }
          }
        `}
      </style>

      {/* Halo first so it sits behind everything else. */}
      <circle cx="20" cy="17" r="16" fill="url(#prism-halo)" className="halo" />

      <polygon points="20,5 30.39,23 9.61,23" strokeWidth="1.5" strokeLinejoin="round" className="prism-glass" />
      <circle cx="20" cy="17" r="3" fill="#ffffff" className="flare" filter="url(#prism-glow)" />
      <path d="M0 17 L20 17" stroke="#ffffff" strokeWidth="1.5" className="beam-white" filter="url(#prism-glow)" strokeLinecap="round" />

      <g className="rays" filter="url(#prism-glow)">
        <path d="M20 17 L55 5" stroke="#ff4757" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
        <path d="M20 17 L55 11" stroke="#ffa502" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
        <path d="M20 17 L55 17" stroke="#2ed573" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
        <path d="M20 17 L55 23" stroke="#1e90ff" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
        <path d="M20 17 L55 29" stroke="#a55eea" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
      </g>
    </svg>
  );
}
