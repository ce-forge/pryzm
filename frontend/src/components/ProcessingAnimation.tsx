import React, { useState } from "react";
import PrismIndicator from "./PrismIndicator";

const PRISM_PHRASES = [
  "Refracting…",
  "Splitting light…",
  "Tracing rays…",
  "Bending photons…",
  "Resolving spectra…",
  "Dispersing thoughts…",
  "Catching wavelengths…",
  "Filtering light…",
  "Decomposing the question…",
  "Reading the prism…",
] as const;

function pickPhrase() {
  return PRISM_PHRASES[Math.floor(Math.random() * PRISM_PHRASES.length)];
}

export default function ProcessingAnimation() {
  const [phrase] = useState(pickPhrase);

  return (
    <div className="flex items-center gap-3 mt-4 mb-2 pl-4">
      <span
        className="text-sm tracking-wide font-medium"
        style={{
          background: 'linear-gradient(90deg, #4b5563 0%, #4b5563 40%, #ffffff 50%, #4b5563 60%, #4b5563 100%)',
          backgroundSize: '200% 100%',
          WebkitBackgroundClip: 'text',
          color: 'transparent',
          animation: 'textShimmer 4s infinite linear'
        }}
      >
        {phrase}
      </span>
      <style>{`
        @keyframes textShimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
      <PrismIndicator size="block" />
    </div>
  );
}
