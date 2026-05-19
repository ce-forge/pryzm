"use client";

import { ReactNode } from "react";

/**
 * Compact at-a-glance panel for the right-hand admin sidebar. Renders a
 * title and a list of label/value rows. Values can be numbers, strings,
 * or arbitrary nodes (badges, links).
 */
export function StatsPanel({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; value: ReactNode }[];
}) {
  return (
    <section className="border border-[#2a2a2c] rounded p-4 bg-[#161617]">
      <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-3">
        {title}
      </h3>
      <dl className="space-y-2 text-sm">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-xs text-gray-400">{r.label}</dt>
            <dd className="font-mono text-[#e3e3e3]">{r.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
