"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

export interface ToolDescriptor {
  name: string;
  description: string;
}

interface Props {
  selected: string[];
  onToggle: (name: string) => void;
  disabled?: boolean;
  filter?: (name: string) => boolean;
}

export function ToolPicker({ selected, onToggle, disabled, filter }: Props) {
  const [available, setAvailable] = useState<ToolDescriptor[]>([]);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/tools")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        if (!cancelled && Array.isArray(data)) setAvailable(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const visible = filter ? available.filter((t) => filter(t.name)) : available;

  if (visible.length === 0) {
    return (
      <p className="text-xs text-gray-500 italic">Loading tool registry…</p>
    );
  }

  return (
    <div className="space-y-1">
      {visible.map((t) => (
        <label
          key={t.name}
          className={
            "flex items-start gap-2 p-1.5 rounded " +
            (disabled
              ? "opacity-60 cursor-not-allowed"
              : "hover:bg-[#2a2a2c]/60 cursor-pointer")
          }
        >
          <input
            type="checkbox"
            checked={selected.includes(t.name)}
            onChange={() => onToggle(t.name)}
            disabled={disabled}
            className="mt-0.5 disabled:cursor-not-allowed"
          />
          <div className="flex-1">
            <div className="text-xs font-mono text-[#e3e3e3]">{t.name}</div>
            <div className="text-xs text-gray-500">{t.description}</div>
          </div>
        </label>
      ))}
    </div>
  );
}
