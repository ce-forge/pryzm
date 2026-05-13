"use client";
import { useState } from "react";
import { setToken } from "@/utils/apiClient";

export function TokenGate({ onConfigured }: { onConfigured: () => void }) {
  const [value, setValue] = useState("");

  const handleSave = () => {
    const trimmed = value.trim();
    if (trimmed) {
      setToken(trimmed);
      onConfigured();
    }
  };

  return (
    <div className="flex h-screen w-full items-center justify-center bg-[#131314] text-[#e3e3e3]">
      <div className="w-full max-w-md space-y-4 p-8">
        <h1 className="text-xl font-semibold">Configure API token</h1>
        <p className="text-sm text-slate-400">
          Pryzm requires a shared bearer token. Get the value from{" "}
          <code className="rounded bg-slate-800 px-1 py-0.5 text-xs">PRYZM_API_TOKEN</code>{" "}
          in the backend&apos;s <code className="text-xs">.env</code> file.
        </p>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSave()}
          placeholder="Paste token"
          className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          autoFocus
        />
        <button
          onClick={handleSave}
          disabled={!value.trim()}
          className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save and continue
        </button>
      </div>
    </div>
  );
}
