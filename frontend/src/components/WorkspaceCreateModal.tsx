"use client";

import React, { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useWorkspaceContext } from "@/context/WorkspaceContext";
import WorkspaceFieldsForm, { useAllowedToolClamp } from "./WorkspaceFieldsForm";
import {
  DEFAULT_WORKSPACE_COLOR,
  type WorkspaceColor,
} from "@/utils/workspaceColors";

interface Props {
  onClose: () => void;
}

export default function WorkspaceCreateModal({ onClose }: Props) {
  const { workspacesApi } = useWorkspaceContext();
  const router = useRouter();
  const clampToCap = useAllowedToolClamp();

  const [startFrom, setStartFrom] = useState<string>("");
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [color, setColor] = useState<WorkspaceColor>(DEFAULT_WORKSPACE_COLOR);
  const [nameError, setNameError] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  // Tracks whether the user has manually edited any field; prevents "Start from"
  // from overwriting intentional edits.
  const dirtyRef = useRef(false);

  const handleStartFromChange = (slug: string) => {
    setStartFrom(slug);
    if (dirtyRef.current) return;
    if (!slug) {
      setName("");
      setPrompt("");
      setEnabledTools([]);
      setColor(DEFAULT_WORKSPACE_COLOR);
      return;
    }
    const source = workspacesApi.workspaces.find((w) => w.slug === slug);
    if (source) {
      setName(source.display_name);
      setPrompt(source.system_prompt);
      setEnabledTools(clampToCap([...source.enabled_tools]));
      setColor((source.color as WorkspaceColor) ?? DEFAULT_WORKSPACE_COLOR);
    }
  };

  const toggleTool = (tool: string) => {
    setEnabledTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool],
    );
    dirtyRef.current = true;
  };

  const handleCreate = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError("Workspace name is required.");
      return;
    }
    setNameError("");
    setIsCreating(true);
    try {
      const ws = await workspacesApi.create({
        display_name: trimmed,
        clone_from: startFrom || null,
        color,
      });
      if (ws) {
        onClose();
        router.replace(`/?session=&workspace=${ws.slug}`);
      }
    } finally {
      setIsCreating(false);
    }
  };

  const modalContent = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1f20] w-full max-w-2xl rounded-2xl border border-[#333537] shadow-2xl flex flex-col overflow-hidden max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center p-5 border-b border-[#333537] bg-[#131314]">
          <h2 className="text-lg font-bold text-[#e3e3e3]">New Workspace</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Start from</label>
            <select
              value={startFrom}
              onChange={(e) => handleStartFromChange(e.target.value)}
              className="w-full bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500"
            >
              <option value="">Start blank</option>
              {workspacesApi.workspaces.map((w) => (
                <option key={w.slug} value={w.slug}>{w.display_name}</option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              Copy settings from an existing workspace as a starting point.
            </p>
          </div>

          <WorkspaceFieldsForm
            name={name}
            onNameChange={(next) => {
              setName(next);
              dirtyRef.current = true;
              if (nameError && next.trim()) setNameError("");
            }}
            nameError={nameError}
            namePlaceholder="e.g. DevOps, Security, Personal"
            color={color}
            onColorChange={(c) => {
              setColor(c);
              dirtyRef.current = true;
            }}
            prompt={prompt}
            onPromptChange={(next) => {
              setPrompt(next);
              dirtyRef.current = true;
            }}
            promptPlaceholder="You are a helpful assistant. Answer the user's questions thoughtfully."
            enabledTools={enabledTools}
            onToggleTool={toggleTool}
          />

          <div className="border-t border-[#333537] pt-6">
            <button
              onClick={handleCreate}
              disabled={isCreating || !name.trim()}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-lg text-sm font-semibold transition-colors"
            >
              {isCreating ? "Creating…" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  // Portal to document.body so the modal escapes the sidebar's transform
  // containing block and overlays the full viewport.
  if (typeof document === "undefined") return null;
  return createPortal(modalContent, document.body);
}
