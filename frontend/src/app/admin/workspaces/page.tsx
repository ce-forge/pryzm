"use client";

import { useState } from "react";
import { AllWorkspacesView } from "@/components/admin/workspaces/AllWorkspacesView";
import { TemplatesView } from "@/components/admin/workspaces/TemplatesView";

type SubTab = "templates" | "workspaces";

export default function AdminWorkspacesPage() {
  const [subTab, setSubTab] = useState<SubTab>("workspaces");
  return (
    <div className="max-w-7xl">
      <div className="flex justify-end mb-4">
        <div className="flex gap-1 border border-[#2a2a2c] rounded p-0.5 bg-[#1e1e1f]">
          <SubTabButton
            label="All workspaces"
            active={subTab === "workspaces"}
            onClick={() => setSubTab("workspaces")}
          />
          <SubTabButton
            label="Templates"
            active={subTab === "templates"}
            onClick={() => setSubTab("templates")}
          />
        </div>
      </div>

      {subTab === "workspaces" ? <AllWorkspacesView /> : <TemplatesView />}
    </div>
  );
}

function SubTabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "text-xs px-3 py-1 rounded " +
        (active
          ? "bg-[#2a2a2c] text-[#e3e3e3]"
          : "text-gray-400 hover:text-[#e3e3e3]")
      }
    >
      {label}
    </button>
  );
}
