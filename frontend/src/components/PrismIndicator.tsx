"use client";

import React from "react";

/**
 * Animated prism + lighthouse beam, used as the live-activity indicator
 * during processing turns. Wraps the SVG in a subtle vertical-float
 * animation independent of the 5s beam/spin cycle so the prism reads as
 * "alive" between beam events instead of static-then-flash.
 *
 * Shared between ProcessingAnimation (non-reasoning turns, displayed with
 * a themed phrase) and ThinkingPanel (reasoning turns, displayed with a
 * `Thinking…` label that expands the reasoning content).
 */
export default function PrismIndicator() {
  return (
    <svg
      viewBox="0 0 60 30"
      className="w-12 h-6 overflow-visible shrink-0 prism-svg"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <filter id="prism-glow" filterUnits="userSpaceOnUse" x="-10" y="-10" width="80" height="50">
          <feGaussianBlur stdDeviation="1" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      <style>
        {`
          /* Container float — runs on its own clock so the prism keeps
             gently rising/settling even during the quiet phase between
             beam events. ~3s sine, 1.5px peak — subtle, never seasick. */
          .prism-svg { animation: prismFloat 3.2s ease-in-out infinite; }

          /* Container-level rays sweep — gives the lighthouse-beacon
             feel as the rainbow shoots out. Rotates a few degrees during
             the exit so the rays appear to pan slightly. */
          .rays { transform-origin: 20px 17px; animation: raysSweep 5s infinite cubic-bezier(0.2, 1, 0.3, 1); }

          .beam-white { stroke-dasharray: 12 50; animation: shootWhite 5s infinite linear; }
          .beam-color { stroke-dasharray: 10 50; animation: shootColor 5s infinite cubic-bezier(0.2, 1, 0.3, 1); }
          .flare { transform-origin: 20px 17px; animation: flareAnim 5s infinite ease-out; }
          .prism-glass {
            transform-origin: 20px 17px;
            animation: prismSpin 5s infinite cubic-bezier(0.34, 1.56, 0.64, 1),
                       prismBreathe 3.2s ease-in-out infinite;
          }

          @keyframes prismFloat {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-1.5px); }
          }

          /* Subtle stroke-opacity pulse during idle phase — the prism
             "breathes" between beam events instead of going dead-quiet. */
          @keyframes prismBreathe {
            0%, 100% { stroke-opacity: 0.55; }
            50% { stroke-opacity: 0.85; }
          }

          @keyframes raysSweep {
            0%, 59.9% { transform: rotate(0deg); }
            60% { transform: rotate(-3deg); }
            70% { transform: rotate(3deg); }
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
