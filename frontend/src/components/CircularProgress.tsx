"use client";
import React from "react";

interface CircularProgressProps {
  /** 0..100. When the value is < 100 the ring renders determinate (fills
   *  clockwise from 12 o'clock). When the value is >= 100 we know bytes
   *  are sent and we're waiting on the server, so the ring switches to
   *  an indeterminate spin to indicate "still working". */
  value: number;
  className?: string;
}

/**
 * Tiny SVG progress ring sized to drop into the existing upload pill's
 * 28x28 icon slot. Stroke inherits the surrounding text color via
 * `currentColor`.
 *
 * One ring shape, two visual modes:
 *   - determinate (value < 100): full circumference visible, stroke-
 *     dashoffset reveals it clockwise.
 *   - indeterminate (value >= 100): a short arc, rotated via
 *     animate-spin, signalling backend processing.
 */
export function CircularProgress({ value, className = "" }: CircularProgressProps) {
  const RADIUS = 10;
  const CIRC = 2 * Math.PI * RADIUS;
  const indeterminate = value >= 100;

  const dashOffset = indeterminate
    ? CIRC * 0.7   // ~30% of the ring visible as the spinning arc
    : CIRC * (1 - Math.max(0, Math.min(value, 100)) / 100);

  return (
    <svg
      viewBox="0 0 24 24"
      className={`${className} ${indeterminate ? "animate-spin" : ""}`}
      style={indeterminate ? { animationDuration: "1s" } : undefined}
      aria-hidden="true"
    >
      {/* track */}
      <circle
        cx="12"
        cy="12"
        r={RADIUS}
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.2}
        strokeWidth={2.5}
      />
      {/* progress arc */}
      <circle
        cx="12"
        cy="12"
        r={RADIUS}
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeDasharray={CIRC}
        strokeDashoffset={dashOffset}
        transform="rotate(-90 12 12)"
        style={{ transition: indeterminate ? undefined : "stroke-dashoffset 200ms linear" }}
      />
    </svg>
  );
}
