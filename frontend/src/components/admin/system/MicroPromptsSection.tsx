"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

export default function MicroPromptsSection() {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [initialPrompts, setInitialPrompts] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);

  useEffect(() => {
    apiFetch("/api/prompts")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && typeof data === "object") {
          setPrompts(data);
          setInitialPrompts(data);
        }
      })
      .catch(() => {});
  }, []);

  const isLoaded = Object.keys(initialPrompts).length > 0;
  const hasChanges =
    isLoaded && JSON.stringify(prompts) !== JSON.stringify(initialPrompts);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await apiFetch("/api/prompts", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prompts),
      });
      setInitialPrompts(prompts);
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch {
      // surface a real error UI later if needed
    }
    setIsSaving(false);
  };

  if (!isLoaded) {
    return (
      <p className="text-xs text-gray-500">Loading micro-prompts…</p>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">
        Customize the Just-In-Time (JIT) instructions injected into the engine
        during edge cases.
      </p>
      <div className="space-y-6">
        {Object.entries(prompts).map(([key, value]) => (
          <div key={key} className="flex flex-col gap-1.5">
            <label className="text-[11px] font-mono text-gray-400 uppercase tracking-wider">
              {key.replace(/_/g, " ")}
            </label>
            <textarea
              value={value}
              onChange={(e) =>
                setPrompts({ ...prompts, [key]: e.target.value })
              }
              className="w-full bg-[#131314] border border-[#333537] text-gray-300 text-sm rounded-lg px-3 py-2 outline-none focus:border-blue-500 min-h-[60px] resize-y custom-scrollbar"
            />
          </div>
        ))}
      </div>
      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={!hasChanges || isSaving}
          className={`px-5 py-2 font-medium rounded-lg text-sm transition-all flex items-center gap-2
            ${showSuccess ? "bg-emerald-600 text-white" :
              hasChanges ? "bg-blue-600 hover:bg-blue-500 text-white" :
              "bg-[#282a2c] text-gray-500 cursor-not-allowed"}`}
        >
          {isSaving
            ? "Saving…"
            : showSuccess
              ? "Saved"
              : "Save changes"}
        </button>
      </div>
    </div>
  );
}
