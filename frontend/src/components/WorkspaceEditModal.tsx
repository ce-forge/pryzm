"use client";

import React, { useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useWorkspaceContext } from "@/context/WorkspaceContext";
import { useAuth } from "@/context/AuthContext";
import { Workspace } from "@/hooks/useWorkspaces";
import ConfirmModal from "./ConfirmModal";
import WorkspaceFieldsForm, { useAllowedToolClamp } from "./WorkspaceFieldsForm";
import {
  DEFAULT_WORKSPACE_COLOR,
  type WorkspaceColor,
} from "@/utils/workspaceColors";

interface Props {
  workspace: Workspace;
  onClose: () => void;
}

export default function WorkspaceEditModal({ workspace, onClose }: Props) {
  const { workspacesApi } = useWorkspaceContext();
  const { user } = useAuth();
  const router = useRouter();
  const clampToCap = useAllowedToolClamp();

  // Edit gate: admins always edit; non-admins only when the workspace's
  // owner_can_edit flag is set.
  const ownerCanEdit =
    user?.workspaces.find((w) => w.slug === workspace.slug)?.owner_can_edit ?? false;
  const canEditWorkspace = !!user?.is_admin || ownerCanEdit;
  const readOnly = !canEditWorkspace;

  const [name, setName] = useState(workspace.display_name);
  const [prompt, setPrompt] = useState(workspace.system_prompt);
  const [enabledTools, setEnabledTools] = useState<string[]>(
    clampToCap(workspace.enabled_tools ?? []),
  );
  const [color, setColor] = useState<WorkspaceColor>(
    (workspace.color as WorkspaceColor) ?? DEFAULT_WORKSPACE_COLOR,
  );

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetDropped, setResetDropped] = useState<string[]>([]);

  // Local state has already been optimistically updated by the field's
  // onChange handler; if the backend PATCH fails, restore from the
  // pre-mutation snapshot of the workspace prop.
  const save = async (patch: Record<string, unknown>) => {
    const snapshot = {
      display_name: workspace.display_name,
      system_prompt: workspace.system_prompt,
      enabled_tools: workspace.enabled_tools,
      color: workspace.color,
    };
    try {
      const ws = await workspacesApi.update(workspace.slug, patch);
      if (!ws) throw new Error("update failed");
    } catch (err) {
      console.error("Workspace update failed", err);
      if ("display_name" in patch) setName(snapshot.display_name);
      if ("system_prompt" in patch) setPrompt(snapshot.system_prompt);
      if ("enabled_tools" in patch) setEnabledTools(clampToCap(snapshot.enabled_tools));
      if ("color" in patch) {
        setColor((snapshot.color as WorkspaceColor) ?? DEFAULT_WORKSPACE_COLOR);
      }
    }
  };

  const toggleTool = (tool: string) => {
    const next = enabledTools.includes(tool)
      ? enabledTools.filter((t) => t !== tool)
      : [...enabledTools, tool];
    setEnabledTools(next);
    save({ enabled_tools: next });
  };

  const handleColorChange = (c: WorkspaceColor) => {
    setColor(c);
    save({ color: c });
  };

  const confirmDeleteWorkspace = async () => {
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
    const result = await workspacesApi.reset(workspace.slug);
    setConfirmReset(false);
    if (result && result.dropped_tools.length > 0) {
      setResetDropped(result.dropped_tools);
      return;
    }
    onClose();
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
          <h2 className="text-lg font-bold text-[#e3e3e3]">
            Workspace · {workspace.display_name}
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

          <WorkspaceFieldsForm
            name={name}
            onNameChange={setName}
            onNameBlur={() => {
              if (name !== workspace.display_name) save({ display_name: name });
            }}
            slug={workspace.slug}
            color={color}
            onColorChange={handleColorChange}
            prompt={prompt}
            onPromptChange={setPrompt}
            onPromptBlur={() => {
              if (prompt !== workspace.system_prompt) save({ system_prompt: prompt });
            }}
            enabledTools={enabledTools}
            onToggleTool={toggleTool}
            readOnly={readOnly}
          />

          {resetDropped.length > 0 && (
            <div className="text-xs px-3 py-2 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300">
              Some tools weren&apos;t restored because your admin restricts your tool
              list: <code className="font-mono">{resetDropped.join(", ")}</code>
            </div>
          )}

          {(canEditWorkspace || user?.is_admin) && (
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
        </div>
      </div>

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
    </div>
  );

  // Portal to document.body so the modal escapes the sidebar's transform
  // containing block and overlays the full viewport.
  if (typeof document === "undefined") return null;
  return createPortal(modalContent, document.body);
}
