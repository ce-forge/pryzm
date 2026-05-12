"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useChatContext } from "@/context/ChatContext";
import { APP_CONFIG } from "@/utils/constants";
import { Workspace } from "@/hooks/useWorkspaces";
import ConfirmModal from "./ConfirmModal";

interface EditProps {
  mode: "edit";
  workspace: Workspace;
  onClose: () => void;
}

interface CreateProps {
  mode: "create";
  workspace?: never;
  onClose: () => void;
}

type Props = EditProps | CreateProps;

export default function WorkspaceSettings({ mode, workspace, onClose }: Props) {
  const { workspacesApi } = useChatContext();
  const router = useRouter();

  // Edit-mode initial values (undefined in create mode until "Start from" is picked).
  const [name, setName] = useState(workspace?.display_name ?? "");
  const [prompt, setPrompt] = useState(workspace?.system_prompt ?? "");
  const [preferredModel, setPreferredModel] = useState<string | null>(workspace?.preferred_model ?? null);
  const [enabledTools, setEnabledTools] = useState<string[]>(workspace?.enabled_tools ?? []);

  const [availableTools, setAvailableTools] = useState<{ name: string; description: string }[]>([]);
  const [installedModels, setInstalledModels] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  // Create-mode state.
  const [startFrom, setStartFrom] = useState<string>(""); // slug or "" for blank
  const [nameError, setNameError] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  // Tracks whether the user has manually edited any field; prevents "Start from"
  // from overwriting intentional edits.
  const dirtyRef = useRef(false);

  useEffect(() => {
    fetch(`${APP_CONFIG.API_URL}/api/tools`).then(r => r.ok ? r.json() : []).then((data) => {
      if (Array.isArray(data)) setAvailableTools(data);
    }).catch(() => {});

    fetch(`${APP_CONFIG.API_URL}/api/models`).then(r => r.json()).then((data) => {
      if (Array.isArray(data)) setInstalledModels(data);
    }).catch(() => {});
  }, []);

  // "Start from" change handler — pre-fills fields if the user hasn't dirtied them.
  const handleStartFromChange = (slug: string) => {
    setStartFrom(slug);
    if (dirtyRef.current) return;
    if (!slug) {
      setName("");
      setPrompt("");
      setPreferredModel(null);
      setEnabledTools([]);
    } else {
      const source = workspacesApi.workspaces.find((w) => w.slug === slug);
      if (source) {
        setName(source.display_name);
        setPrompt(source.system_prompt);
        setPreferredModel(source.preferred_model);
        setEnabledTools([...source.enabled_tools]);
      }
    }
  };

  // Edit-mode helpers.
  const save = (patch: Record<string, unknown>) => {
    if (mode === "edit") workspacesApi.update(workspace.slug, patch);
  };

  const toggleTool = (tool: string) => {
    const next = enabledTools.includes(tool)
      ? enabledTools.filter((t) => t !== tool)
      : [...enabledTools, tool];
    setEnabledTools(next);
    if (mode === "edit") save({ enabled_tools: next });
    else dirtyRef.current = true;
  };

  const confirmDeleteWorkspace = async () => {
    if (mode !== "edit") return;
    const result = await workspacesApi.remove(workspace.slug);
    setConfirmDelete(false);
    if (result) {
      const remaining = workspacesApi.workspaces.filter((w) => w.slug !== workspace.slug);
      const next = remaining[0];
      if (next) router.replace(`/?workspace=${next.slug}`);
    }
    onClose();
  };

  const performReset = async () => {
    if (mode !== "edit") return;
    await workspacesApi.reset(workspace.slug);
    setConfirmReset(false);
    onClose();
  };

  // Create-mode submit.
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
      });
      if (ws) {
        onClose();
        router.replace(`/?session=&workspace=${ws.slug}`);
      }
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#1e1f20] w-full max-w-2xl rounded-2xl border border-[#333537] shadow-2xl flex flex-col overflow-hidden max-h-[85vh]">

        {/* Header */}
        <div className="flex justify-between items-center p-5 border-b border-[#333537] bg-[#131314]">
          <h2 className="text-lg font-bold text-[#e3e3e3]">
            {mode === "create" ? "New Workspace" : `Workspace · ${workspace.display_name}`}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">

          {/* Create mode: "Start from" selector */}
          {mode === "create" && (
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
              <p className="text-xs text-gray-500 mt-1">Copy settings from an existing workspace as a starting point.</p>
            </div>
          )}

          {/* Display name */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Display name</label>
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                dirtyRef.current = true;
                if (nameError && e.target.value.trim()) setNameError("");
              }}
              onBlur={() => {
                if (mode === "edit" && name !== workspace.display_name) save({ display_name: name });
              }}
              className={`w-full bg-[#131314] border text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500 transition-colors ${nameError ? "border-red-500" : "border-[#333537]"}`}
              placeholder={mode === "create" ? "e.g. DevOps, Security, Personal" : undefined}
            />
            {mode === "create" && nameError && (
              <p className="text-xs text-red-400 mt-1">{nameError}</p>
            )}
            {mode === "edit" && (
              <p className="text-xs text-gray-500 mt-1">Slug: <code className="font-mono">{workspace.slug}</code> (immutable)</p>
            )}
          </div>

          {/* System prompt */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">System prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                dirtyRef.current = true;
              }}
              onBlur={() => {
                if (mode === "edit" && prompt !== workspace.system_prompt) save({ system_prompt: prompt });
              }}
              rows={10}
              className="w-full bg-[#131314] border border-[#333537] text-gray-300 text-sm rounded-lg px-3 py-2 outline-none focus:border-blue-500 font-mono resize-y custom-scrollbar"
            />
            <p className="text-xs text-gray-500 mt-1">Use <code>{"{tool_names}"}</code> to substitute the enabled tool list.</p>
          </div>

          {/* Preferred model */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Preferred model</label>
            <select
              value={preferredModel ?? ""}
              onChange={(e) => {
                const v = e.target.value || null;
                setPreferredModel(v);
                dirtyRef.current = true;
                if (mode === "edit") save({ preferred_model: v });
              }}
              className="w-full bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500"
            >
              <option value="">Use default model (current global picker)</option>
              {installedModels.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          {/* Enabled tools */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Enabled tools</label>
            <p className="text-xs text-gray-500 mb-3">
              Toggle which tools the model can call from this workspace. The model decides when to call them based on each tool&apos;s own description.
            </p>
            <div className="space-y-2">
              {availableTools.length === 0 && (
                <p className="text-xs text-gray-500 italic">Loading tool registry&hellip;</p>
              )}
              {availableTools.map((t) => (
                <label key={t.name} className="flex items-start gap-3 p-2 rounded hover:bg-[#282a2c]/40 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enabledTools.includes(t.name)}
                    onChange={() => toggleTool(t.name)}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-mono text-[#e3e3e3]">{t.name}</div>
                    <div className="text-xs text-gray-500">{t.description}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Edit-mode danger zone */}
          {mode === "edit" && (
            <div className="border-t border-[#333537] pt-6 space-y-3">
              {workspace.is_builtin && (
                <button
                  onClick={() => setConfirmReset(true)}
                  className="w-full bg-[#282a2c] hover:bg-[#333537] text-gray-300 px-4 py-2 rounded-lg text-sm font-medium"
                >
                  Reset to default
                </button>
              )}
              <button
                onClick={() => setConfirmDelete(true)}
                className="w-full bg-red-900/30 hover:bg-red-900/50 border border-red-500/30 text-red-400 px-4 py-2 rounded-lg text-sm font-medium"
              >
                Delete workspace
              </button>
            </div>
          )}

          {/* Create-mode submit */}
          {mode === "create" && (
            <div className="border-t border-[#333537] pt-6">
              <button
                onClick={handleCreate}
                disabled={isCreating || !name.trim()}
                className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-lg text-sm font-semibold transition-colors"
              >
                {isCreating ? "Creating…" : "Create"}
              </button>
            </div>
          )}
        </div>
      </div>

      {mode === "edit" && (
        <>
          <ConfirmModal
            isOpen={confirmDelete}
            title={`Delete ${workspace.display_name}?`}
            description="This permanently deletes the workspace and all of its sessions, folders, and uploaded documents."
            onConfirm={confirmDeleteWorkspace}
            onCancel={() => setConfirmDelete(false)}
          />

          <ConfirmModal
            isOpen={confirmReset}
            title="Reset to default?"
            description={`This restores ${workspace.display_name}'s prompt, tools, and model pin to the original defaults. Your edits will be lost.`}
            onConfirm={performReset}
            onCancel={() => setConfirmReset(false)}
            danger={false}
            confirmText="Reset"
          />
        </>
      )}
    </div>
  );
}
