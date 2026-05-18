"use client";

/**
 * Per-username SVG identicon. Symmetric 5x5 grid of pixel-art tiles
 * generated from a hash of the username. Used as the user avatar in
 * the sidebar header.
 */

function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  }
  return h;
}

export default function Identicon({
  seed,
  size = 24,
}: {
  seed: string;
  size?: number;
}) {
  const h = hashString(seed || "anon");
  const hue = h % 360;
  const fg = `hsl(${hue}, 65%, 55%)`;
  const bg = "#1e1f20";

  // Build a 5-column-wide grid where columns 0,1,2 are independent and 3,4 mirror 1,0.
  // 5 rows x 3 unique cols = 15 bits drawn from the hash.
  const grid: boolean[][] = [];
  let bits = h;
  for (let row = 0; row < 5; row++) {
    const r: boolean[] = [];
    for (let col = 0; col < 3; col++) {
      r.push((bits & 1) === 1);
      bits >>>= 1;
    }
    r.push(r[1], r[0]);
    grid.push(r);
  }

  const cell = size / 5;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
      <rect width={size} height={size} fill={bg} rx={size * 0.12} />
      {grid.flatMap((row, y) =>
        row.map((on, x) =>
          on ? (
            <rect
              key={`${y}-${x}`}
              x={x * cell}
              y={y * cell}
              width={cell}
              height={cell}
              fill={fg}
            />
          ) : null,
        ),
      )}
    </svg>
  );
}
