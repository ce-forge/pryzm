"use client";

import ModelsSection from "@/components/SettingsModels";
import MicroPromptsSection from "@/components/MicroPromptsSection";

export default function AdminSystemPage() {
  return (
    <div className="max-w-4xl space-y-10">
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
  );
}
