"use client";

import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useWorkspaceContext } from "@/context/WorkspaceContext";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiClient";
import { Workspace } from "@/hooks/useWorkspaces";
import { withRollback } from "@/utils/withRollback";
import ConfirmModal from "./ConfirmModal";
import {
  WORKSPACE_COLOR_NAMES,
  DEFAULT_WORKSPACE_COLOR,
  getWorkspaceColorClasses,
  type WorkspaceColor,
} from "@/utils/workspaceColors";
import { WorkspaceSprite } from "@/utils/workspaceSprites";

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
  const { workspacesApi } = useWorkspaceContext();
  const { user } = useAuth();
  const router = useRouter();

  // Edit gate: admins always edit; non-admins only when the workspace's
  // owner_can_edit flag is set. Create mode is unaffected (gated upstream by
  // can_create_workspaces in the switcher).
  const ownerCanEdit = mode === "edit"
    ? (user?.workspaces.find((w) => w.slug === workspace.slug)?.owner_can_edit ?? false)
    : true;
  const canEditWorkspace = mode !== "edit" || !!user?.is_admin || ownerCanEdit;
  const readOnly = mode === "edit" && !canEditWorkspace;

  const [name, setName] = useState(workspace?.display_name ?? "");
  const [prompt, setPrompt] = useState(workspace?.system_prompt ?? "");
  const [enabledTools, setEnabledTools] = useState<string[]>(workspace?.enabled_tools ?? []);
  const [color, setColor] = useState<WorkspaceColor>(
    (workspace?.color as WorkspaceColor) ?? DEFAULT_WORKSPACE_COLOR
  );

  const [availableTools, setAvailableTools] = useState<{ name: string; description: string }[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  // Create-mode state.
  const [startFrom, setStartFrom] = useState<string>("");
  const [nameError, setNameError] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  // Tracks whether the user has manually edited any field; prevents "Start from"
  // from overwriting intentional edits.
  const dirtyRef = useRef(false);

  useEffect(() => {
    apiFetch("/api/tools").then(r => r.ok ? r.json() : []).then((data) => {
      if (Array.isArray(data)) setAvailableTools(data);
    }).catch(() => {});
  }, []);

  // "Start from" change handler — pre-fills fields if the user hasn't dirtied them.
  const handleStartFromChange = (slug: string) => {
    setStartFrom(slug);
    if (dirtyRef.current) return;
    if (!slug) {
      setName("");
      setPrompt("");
      setEnabledTools([]);
      setColor(DEFAULT_WORKSPACE_COLOR);
    } else {
      const source = workspacesApi.workspaces.find((w) => w.slug === slug);
      if (source) {
        setName(source.display_name);
        setPrompt(source.system_prompt);
        setEnabledTools([...source.enabled_tools]);
        setColor((source.color as WorkspaceColor) ?? DEFAULT_WORKSPACE_COLOR);
      }
    }
  };

  // Edit-mode helpers. Local state has already been optimistically updated by
  // the field's onChange handler; if the backend PATCH fails, restore from the
  // pre-mutation snapshot of the workspace prop.
  const save = async (patch: Record<string, unknown>) => {
    if (mode !== "edit") return;
    const snapshot = {
      display_name: workspace.display_name,
      system_prompt: workspace.system_prompt,
      enabled_tools: workspace.enabled_tools,
      color: workspace.color,
    };
    try {
      await withRollback(
        () => { /* local state already applied via the field's setter */ },
        () => {
          if ("display_name" in patch) setName(snapshot.display_name);
          if ("system_prompt" in patch) setPrompt(snapshot.system_prompt);
          if ("enabled_tools" in patch) setEnabledTools(snapshot.enabled_tools);
          if ("color" in patch) setColor((snapshot.color as WorkspaceColor) ?? DEFAULT_WORKSPACE_COLOR);
        },
        async () => {
          const ws = await workspacesApi.update(workspace.slug, patch);
          if (!ws) throw new Error("update failed");
          return ws;
        },
      );
    } catch (err) {
      console.error("Workspace update failed", err);
    }
  };

  const toggleTool = (tool: string) => {
    const next = enabledTools.includes(tool)
      ? enabledTools.filter((t) => t !== tool)
      : [...enabledTools, tool];
    setEnabledTools(next);
    if (mode === "edit") save({ enabled_tools: next });
    else dirtyRef.current = true;
  };

  const handleColorChange = (c: WorkspaceColor) => {
    setColor(c);
    dirtyRef.current = true;
    if (mode === "edit") save({ color: c });
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

          {readOnly && (
            <p className="text-xs text-gray-500">
              This workspace is read-only. Contact your admin to enable editing.
            </p>
          )}

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
              disabled={readOnly}
              readOnly={readOnly}
              className={`w-full bg-[#131314] border text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500 transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${nameError ? "border-red-500" : "border-[#333537]"}`}
              placeholder={mode === "create" ? "e.g. DevOps, Security, Personal" : undefined}
            />
            {mode === "create" && nameError && (
              <p className="text-xs text-red-400 mt-1">{nameError}</p>
            )}
            {mode === "edit" && (
              <p className="text-xs text-gray-500 mt-1">Slug: <code className="font-mono">{workspace.slug}</code> (immutable)</p>
            )}
          </div>

          {/* Workspace sprite */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Workspace sprite</label>
            <div className="flex items-center gap-2">
              {WORKSPACE_COLOR_NAMES.map((c) => {
                const isSelected = color === c;
                const classes = getWorkspaceColorClasses(c);
                return (
                  <button
                    key={c}
                    type="button"
                    onClick={() => handleColorChange(c)}
                    disabled={readOnly}
                    className={`w-10 h-10 rounded-lg flex items-center justify-center transition-all ${classes.text} ${
                      isSelected
                        ? `ring-2 ring-offset-2 ring-offset-[#1e1f20] ${classes.ring} bg-[#282a2c]`
                        : "hover:bg-[#282a2c]/60"
                    } disabled:opacity-60 disabled:cursor-not-allowed`}
                    title={c}
                    aria-label={`${c} sprite`}
                  >
                    <WorkspaceSprite color={c} className="w-6 h-6" />
                  </button>
                );
              })}
            </div>
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
              disabled={readOnly}
              readOnly={readOnly}
              className="w-full bg-[#131314] border border-[#333537] text-gray-300 text-sm rounded-lg px-3 py-2 outline-none focus:border-blue-500 font-mono resize-y custom-scrollbar disabled:opacity-60 disabled:cursor-not-allowed"
            />
            <p className="text-xs text-gray-500 mt-1">Use <code>{"{tool_names}"}</code> to substitute the enabled tool list.</p>
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
                <label key={t.name} className={`flex items-start gap-3 p-2 rounded ${readOnly ? "opacity-60 cursor-not-allowed" : "hover:bg-[#282a2c]/40 cursor-pointer"}`}>
                  <input
                    type="checkbox"
                    checked={enabledTools.includes(t.name)}
                    onChange={() => toggleTool(t.name)}
                    disabled={readOnly}
                    className="mt-1 disabled:cursor-not-allowed"
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
          {mode === "edit" && (canEditWorkspace || user?.is_admin) && (
            <div className="border-t border-[#333537] pt-6 space-y-3">
              {workspace.is_builtin && canEditWorkspace && (
                <button
                  onClick={() => setConfirmReset(true)}
                  className="w-full bg-[#282a2c] hover:bg-[#333537] text-gray-300 px-4 py-2 rounded-lg text-sm font-medium"
                >
                  Reset to default
                </button>
              )}
              {!workspace.is_builtin && user?.is_admin && (
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="w-full bg-red-900/30 hover:bg-red-900/50 border border-red-500/30 text-red-400 px-4 py-2 rounded-lg text-sm font-medium"
                >
                  Delete workspace
                </button>
              )}
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

  // Portal to document.body so the modal escapes the sidebar's transform
  // containing block and overlays the full viewport.
  if (typeof document === "undefined") return null;
  return createPortal(modalContent, document.body);
}
