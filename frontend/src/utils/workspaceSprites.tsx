import React from "react";
import type { WorkspaceColor } from "./workspaceColors";

type PixelGrid = readonly (readonly (0 | 1)[])[];

// Blue — window/frame
const FRAME: PixelGrid = [
  [1, 1, 1, 1, 1],
  [1, 0, 0, 0, 1],
  [1, 0, 1, 0, 1],
  [1, 0, 0, 0, 1],
  [1, 1, 1, 1, 1],
];

// Orange — flame
const FLAME: PixelGrid = [
  [0, 0, 1, 0, 0],
  [0, 1, 1, 1, 0],
  [1, 1, 0, 1, 1],
  [1, 1, 1, 1, 1],
  [0, 1, 1, 1, 0],
];

// Emerald — pine tree
const TREE: PixelGrid = [
  [0, 0, 1, 0, 0],
  [0, 1, 1, 1, 0],
  [1, 1, 1, 1, 1],
  [0, 0, 1, 0, 0],
  [0, 0, 1, 0, 0],
];

// Red — heart
const HEART: PixelGrid = [
  [0, 1, 0, 1, 0],
  [1, 1, 1, 1, 1],
  [1, 1, 1, 1, 1],
  [0, 1, 1, 1, 0],
  [0, 0, 1, 0, 0],
];

// Amber — 5-point star
const STAR: PixelGrid = [
  [0, 0, 1, 0, 0],
  [1, 1, 1, 1, 1],
  [0, 1, 1, 1, 0],
  [1, 1, 0, 1, 1],
  [1, 0, 0, 0, 1],
];

// Violet — crescent moon
const MOON: PixelGrid = [
  [0, 1, 1, 1, 0],
  [1, 1, 0, 0, 0],
  [1, 1, 0, 0, 0],
  [1, 1, 0, 0, 0],
  [0, 1, 1, 1, 0],
];

// Cyan — water drop
const DROP: PixelGrid = [
  [0, 0, 1, 0, 0],
  [0, 1, 1, 1, 0],
  [1, 1, 1, 1, 1],
  [1, 1, 1, 1, 1],
  [0, 1, 1, 1, 0],
];

// Pink — flower
const FLOWER: PixelGrid = [
  [1, 0, 1, 0, 1],
  [0, 1, 1, 1, 0],
  [1, 1, 1, 1, 1],
  [0, 1, 1, 1, 0],
  [1, 0, 1, 0, 1],
];

const SPRITE_GRIDS: Record<WorkspaceColor, PixelGrid> = {
  blue:    FRAME,
  orange:  FLAME,
  emerald: TREE,
  red:     HEART,
  amber:   STAR,
  violet:  MOON,
  cyan:    DROP,
  pink:    FLOWER,
};

interface WorkspaceSpriteProps {
  color: string | null | undefined;
  className?: string;
}

export function WorkspaceSprite({ color, className }: WorkspaceSpriteProps) {
  const key = (color && color in SPRITE_GRIDS ? color : "blue") as WorkspaceColor;
  const grid = SPRITE_GRIDS[key];
  return (
    <svg
      viewBox="0 0 10 10"
      className={className}
      fill="currentColor"
      style={{ shapeRendering: "crispEdges" }}
      aria-hidden="true"
    >
      {grid.flatMap((row, y) =>
        row.map((cell, x) =>
          cell ? <rect key={`${x}-${y}`} x={x * 2 + 0.2} y={y * 2 + 0.2} width="1.6" height="1.6" /> : null
        )
      )}
    </svg>
  );
}
