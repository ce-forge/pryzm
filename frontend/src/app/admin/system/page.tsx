"use client";

import { useEffect, useState } from "react";
import ModelsSection from "@/components/admin/system/SettingsModels";
import MicroPromptsSection from "@/components/admin/system/MicroPromptsSection";
import { StatsPanel } from "@/components/admin/StatsPanel";
import { apiFetch } from "@/utils/apiClient";

interface ModelRow {
  id: string;
  group?: string;
}

export default function AdminSystemPage() {
  const [models, setModels] = useState<ModelRow[]>([]);
  const [promptCount, setPromptCount] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/admin/models")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        if (!cancelled && Array.isArray(data)) setModels(data);
      })
      .catch(() => {});
    apiFetch("/api/prompts")
      .then((r) => (r.ok ? r.json() : {}))
      .then((data) => {
        if (!cancelled && data && typeof data === "object") {
          setPromptCount(Object.keys(data).length);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const alwaysOn = models.filter((m) => m.group === "always-on").length;
  const chat = models.filter((m) => m.group === "chat").length;

  return (
    <div className="flex gap-6 max-w-7xl">
      <div className="flex-1 min-w-0 space-y-10">
        <p className="text-xs text-gray-400">
          Engine-wide settings: which models are available + the micro-prompts
          that all workspaces share. Domain-specific prompts live on the
          individual workspace.
        </p>

        <ModelsSection />

        <section>
          <h3 className="text-sm font-semibold mb-3 text-gray-300">
            Micro-prompts
          </h3>
          <MicroPromptsSection />
        </section>
      </div>

      <aside className="hidden xl:block w-72 shrink-0 space-y-4">
        <StatsPanel
          title="At a glance"
          rows={[
            { label: "Models", value: models.length },
            { label: "Always-on", value: alwaysOn },
            { label: "Chat", value: chat },
            { label: "Micro-prompts", value: promptCount },
          ]}
        />
      </aside>
    </div>
  );
}
