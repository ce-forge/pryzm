"use client";

import React, { useState, useRef } from "react";
import { useChatContext } from "@/context/ChatContext";
import { useOnClickOutside } from "@/hooks/useOnClickOutside";
import InlineCreateForm from "./InlineCreateForm";
import WorkspaceSettings from "./WorkspaceSettings";

export default function WorkspaceSwitcher() {
  const { workspacesApi, activeWorkspace, session } = useChatContext();
  const [isOpen, setIsOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [cloneFrom, setCloneFrom] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOnClickOutside(ref, () => { setIsOpen(false); setIsCreating(false); });

  const switchTo = (slug: string) => {
    setIsOpen(false);
    session.navigateToSession("");
    window.location.search = `?workspace=${slug}`;
  };

  const handleCreate = async (display_name: string) => {
    const ws = await workspacesApi.create({ display_name, clone_from: cloneFrom });
    setIsCreating(false);
    setCloneFrom(null);
    if (ws) switchTo(ws.slug);
  };

  return (
    <div className="px-4 mb-4 relative" ref={ref}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between bg-[#131314] border border-[#333537] rounded-lg px-3 py-2 text-sm text-[#e3e3e3] hover:bg-[#282a2c]/50 transition-colors"
      >
        <span className="truncate font-medium">{activeWorkspace?.display_name ?? "Loading..."}</span>
        <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute left-4 right-4 top-full mt-1 bg-[#1e1f20] border border-[#333537] rounded-lg shadow-2xl z-50 overflow-hidden">
          <div className="max-h-64 overflow-y-auto custom-scrollbar">
            {workspacesApi.workspaces.map((w) => (
              <button
                key={w.slug}
                onClick={() => switchTo(w.slug)}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-[#282a2c] flex items-center justify-between ${
                  activeWorkspace?.slug === w.slug ? "bg-[#282a2c]/50 text-blue-400" : "text-gray-300"
                }`}
              >
                <span className="truncate">{w.display_name}</span>
                {w.is_builtin && <span className="text-[9px] uppercase tracking-wider text-gray-500">built-in</span>}
              </button>
            ))}
          </div>

          <div className="border-t border-[#333537]">
            {isCreating ? (
              <div className="p-2 space-y-2">
                <select
                  value={cloneFrom ?? ""}
                  onChange={(e) => setCloneFrom(e.target.value || null)}
                  className="w-full bg-[#131314] text-[#e3e3e3] text-xs px-2 py-1 rounded border border-[#333537]"
                >
                  <option value="">Blank (default)</option>
                  {workspacesApi.workspaces.map((w) => (
                    <option key={w.slug} value={w.slug}>Clone from {w.display_name}</option>
                  ))}
                </select>
                <InlineCreateForm
                  placeholder="Workspace name"
                  onSubmit={handleCreate}
                  onCancel={() => { setIsCreating(false); setCloneFrom(null); }}
                />
              </div>
            ) : (
              <button
                onClick={() => setIsCreating(true)}
                className="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-[#282a2c] hover:text-[#e3e3e3]"
              >
                + New workspace
              </button>
            )}
            <button
              onClick={() => { setIsOpen(false); setShowSettings(true); }}
              disabled={!activeWorkspace}
              className="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-[#282a2c] hover:text-[#e3e3e3] border-t border-[#333537] disabled:opacity-50"
            >
              &#9881; Workspace settings
            </button>
          </div>
        </div>
      )}

      {showSettings && activeWorkspace && (
        <WorkspaceSettings
          workspace={activeWorkspace}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
