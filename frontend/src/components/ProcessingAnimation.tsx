import React, { useState } from "react";

interface ProcessingAnimationProps {
  /**
   * Label rendered next to the prism animation. Lowercase by convention.
   * "reflecting…" is the small-model default; "focusing…" indicates the
   * large-tier model is mid-reasoning (reasoning_content streaming).
   */
  label?: string;
  /**
   * Live reasoning_content text. When set, an inline "Thinking" disclosure
   * pill renders next to the prism; clicking it expands the reasoning panel
   * below. Empty/undefined hides the pill entirely.
   */
  reasoning?: string | null;
}

export default function ProcessingAnimation({ label = "reflecting…", reasoning }: ProcessingAnimationProps) {
  const [open, setOpen] = useState(false);
  const hasReasoning = !!reasoning;

  return (
    <div className="mt-4 mb-2 pl-4">
      <div className="flex items-center">

      {/* 1. LABEL ON THE LEFT */}
      <span
        className="text-sm tracking-wide font-medium mr-4"
        style={{
          background: 'linear-gradient(90deg, #4b5563 0%, #4b5563 40%, #ffffff 50%, #4b5563 60%, #4b5563 100%)',
          backgroundSize: '200% 100%',
          WebkitBackgroundClip: 'text',
          color: 'transparent',
          animation: 'textShimmer 5s infinite linear'
        }}
      >
        {label}
      </span>
      <style>{`
        @keyframes textShimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>

      {/* 2. SVG ON THE RIGHT */}
      <svg viewBox="0 0 60 30" className="w-12 h-6 overflow-visible" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <filter id="premium-glow" filterUnits="userSpaceOnUse" x="-10" y="-10" width="80" height="50">
            <feGaussianBlur stdDeviation="1" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>
        
        <style>
          {`
            /* All elements share the exact same 5s master clock */
            .beam-white { stroke-dasharray: 12 50; animation: shootWhite 5s infinite linear; }
            .beam-color { stroke-dasharray: 10 50; animation: shootColor 5s infinite cubic-bezier(0.2, 1, 0.3, 1); }
            .flare { transform-origin: 20px 17px; animation: flareAnim 5s infinite ease-out; }
            .prism-glass { transform-origin: 20px 17px; animation: prismSpin 5s infinite cubic-bezier(0.34, 1.56, 0.64, 1); }

            /* 50% to 60%: White beam travels from left to center */
            @keyframes shootWhite {
              0%, 50% { stroke-dashoffset: 12; opacity: 0; }
              51% { stroke-dashoffset: 9; opacity: 1; }
              60% { stroke-dashoffset: -8; opacity: 1; }
              60.1%, 100% { stroke-dashoffset: -8; opacity: 0; }
            }

            /* 60% to 75%: Rainbows shoot out immediately as white beam hits */
            @keyframes shootColor {
              0%, 59.9% { stroke-dashoffset: 10; opacity: 0; }
              60% { stroke-dashoffset: 10; opacity: 1; }
              70% { stroke-dashoffset: -37; opacity: 1; }
              72%, 100% { stroke-dashoffset: -37; opacity: 0; }
            }

            /* 60% to 65%: Center impact flash */
            @keyframes flareAnim {
              0%, 59.9% { transform: scale(0); opacity: 0; }
              60% { transform: scale(1.5); opacity: 1; }
              65%, 100% { transform: scale(0); opacity: 0; }
            }

            /* 60% to 75%: Prism flashes and does a snappy 120-degree spin */
            @keyframes prismSpin {
              0%, 59.9% { transform: rotate(0deg); fill: rgba(255,255,255,0); stroke: #4b5563; }
              60% { fill: rgba(255,255,255,0.4); stroke: #ffffff; transform: rotate(0deg); }
              65% { fill: rgba(255,255,255,0.1); stroke: #9ca3af; transform: rotate(30deg); }
              75%, 100% { transform: rotate(120deg); fill: rgba(255,255,255,0); stroke: #4b5563; }
            }
          `}
        </style>

        {/* Perfect Equilateral Prism */}
        <polygon points="20,5 30.39,23 9.61,23" strokeWidth="1.5" strokeLinejoin="round" className="prism-glass" />

        {/* Center Impact Flare */}
        <circle cx="20" cy="17" r="3" fill="#ffffff" className="flare" filter="url(#premium-glow)" />

        {/* White Beam Packet In */}
        <path d="M0 17 L20 17" stroke="#ffffff" strokeWidth="1.5" className="beam-white" filter="url(#premium-glow)" strokeLinecap="round" />

        {/* Vibrant Rainbow Packets Out */}
        <g filter="url(#premium-glow)">
          <path d="M20 17 L55 5" stroke="#ff4757" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
          <path d="M20 17 L55 11" stroke="#ffa502" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
          <path d="M20 17 L55 17" stroke="#2ed573" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
          <path d="M20 17 L55 23" stroke="#1e90ff" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
          <path d="M20 17 L55 29" stroke="#a55eea" strokeWidth="1.5" className="beam-color" strokeLinecap="round" />
        </g>
      </svg>

      {/* 3. INLINE THINKING DISCLOSURE — sits on the same row as the prism
          so the user sees the reasoning indicator and the "model is working"
          animation as a single unit, the moment reasoning_content starts. */}
      {hasReasoning && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="ml-4 flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          <span className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
          <span>Thinking</span>
        </button>
      )}
      </div>
      {hasReasoning && open && (
        <div className="mt-2 px-3 py-2 rounded-lg border border-[#333537] bg-[#1a1b1c] text-[12px] text-gray-400 leading-relaxed whitespace-pre-wrap max-w-3xl">
          {reasoning}
        </div>
      )}
    </div>
  );
}