"use client";

import React, { useState } from "react";

interface Props {
  placeholder: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
  autoFocus?: boolean;
}

/**
 * Small inline form for "+ <thing>" flows. Renders an autofocus input that
 * submits on Enter or blur (trimmed, non-empty) and cancels on Escape.
 * Shared between SessionDirectory's `+ Folder` and WorkspaceSwitcher's
 * `+ Workspace` — same shape, same behaviour, single place to fix bugs.
 */
export default function InlineCreateForm({ placeholder, onSubmit, onCancel, autoFocus = true }: Props) {
  const [value, setValue] = useState("");

  const submit = () => {
    const cleaned = value.trim();
    if (!cleaned) {
      onCancel();
      return;
    }
    onSubmit(cleaned);
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="px-3 py-1.5"
    >
      <input
        autoFocus={autoFocus}
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onBlur={submit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
        className="w-full bg-[#131314] text-[#e3e3e3] text-sm px-2 py-0.5 rounded outline-none border border-blue-500/50"
      />
    </form>
  );
}
