import React, { useState } from "react";
import PrismIndicator from "./PrismIndicator";

const PRISM_PHRASES = [
  "Refracting",
  "Splitting light",
  "Tracing rays",
  "Bending photons",
  "Resolving spectra",
  "Dispersing thoughts",
  "Catching wavelengths",
  "Filtering light",
  "Decomposing the question",
  "Reading the prism",
] as const;

function pickPhrase() {
  return PRISM_PHRASES[Math.floor(Math.random() * PRISM_PHRASES.length)];
}

export default function ProcessingAnimation() {
  const [phrase] = useState(pickPhrase);

  return (
    <div className="flex items-center gap-2 mt-4 mb-2 pl-4">
      <PrismIndicator size="block" />
      <span
        className="text-[13px] tracking-[0.01em] processing-shimmer"
      >
        {phrase}…
      </span>
      <style>{`
        .processing-shimmer {
          background-image: linear-gradient(
            90deg,
            rgba(107, 114, 128, 1) 0%,
            rgba(107, 114, 128, 1) 44%,
            rgba(229, 231, 235, 1) 50%,
            rgba(107, 114, 128, 1) 56%,
            rgba(107, 114, 128, 1) 100%
          );
          background-size: 240% 100%;
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
          animation: processingShimmer 3.2s linear infinite;
        }
        @keyframes processingShimmer {
          0% { background-position: 240% 0; }
          100% { background-position: -140% 0; }
        }
      `}</style>
    </div>
  );
}
