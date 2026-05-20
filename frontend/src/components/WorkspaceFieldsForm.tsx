"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiClient";
import {
  WORKSPACE_COLOR_NAMES,
  getWorkspaceColorClasses,
  type WorkspaceColor,
} from "@/utils/workspaceColors";
import { WorkspaceSprite } from "@/utils/workspaceSprites";

interface Props {
  name: string;
  onNameChange: (next: string) => void;
  onNameBlur?: () => void;
  nameError?: string;
  namePlaceholder?: string;
  slug?: string;

  color: WorkspaceColor;
  onColorChange: (next: WorkspaceColor) => void;

  prompt: string;
  onPromptChange: (next: string) => void;
  onPromptBlur?: () => void;
  promptPlaceholder?: string;

  enabledTools: string[];
  onToggleTool: (tool: string) => void;

  readOnly?: boolean;
}

/**
 * Shared field rendering for the workspace create + edit modals. Owns the
 * tool-registry fetch and the admin/allowed-tools cap filtering so both
 * modals get identical gating without duplicated code.
 */
export default function WorkspaceFieldsForm({
  name,
  onNameChange,
  onNameBlur,
  nameError,
  namePlaceholder,
  slug,
  color,
  onColorChange,
  prompt,
  onPromptChange,
  onPromptBlur,
  promptPlaceholder,
  enabledTools,
  onToggleTool,
  readOnly = false,
}: Props) {
  const { user } = useAuth();
  const [availableTools, setAvailableTools] = useState<{ name: string; description: string }[]>([]);

  // Cap filter: admins and uncapped users see every tool; capped non-admins
  // see only tools in their allowed_tools list.
  const allowedToolSet = useMemo<Set<string> | null>(() => {
    if (!user || user.is_admin) return null;
    const cap = user.allowed_tools ?? [];
    if (cap.length === 0) return null;
    return new Set(cap);
  }, [user]);

  useEffect(() => {
    apiFetch("/api/tools")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        if (Array.isArray(data)) setAvailableTools(data);
      })
      .catch(() => {});
  }, []);

  return (
    <>
      {/* Display name */}
      <div>
        <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Display name</label>
        <input
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          onBlur={onNameBlur}
          disabled={readOnly}
          readOnly={readOnly}
          className={`w-full bg-[#131314] border text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500 transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${nameError ? "border-red-500" : "border-[#333537]"}`}
          placeholder={namePlaceholder}
        />
        {nameError && <p className="text-xs text-red-400 mt-1">{nameError}</p>}
        {slug && (
          <p className="text-xs text-gray-500 mt-1">
            Slug: <code className="font-mono">{slug}</code> (immutable)
          </p>
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
                onClick={() => onColorChange(c)}
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
          onChange={(e) => onPromptChange(e.target.value)}
          onBlur={onPromptBlur}
          rows={10}
          disabled={readOnly}
          readOnly={readOnly}
          placeholder={promptPlaceholder}
          className="w-full bg-[#131314] border border-[#333537] text-gray-300 text-sm rounded-lg px-3 py-2 outline-none focus:border-blue-500 font-mono resize-y custom-scrollbar disabled:opacity-60 disabled:cursor-not-allowed"
        />
        <p className="text-xs text-gray-500 mt-1">
          Use <code>{"{tool_names}"}</code> to substitute the enabled tool list.
        </p>
      </div>

      {/* Enabled tools */}
      <div>
        <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Enabled tools</label>
        <p className="text-xs text-gray-500 mb-3">
          Toggle which tools the model can call from this workspace. The model decides when to
          call them based on each tool&apos;s own description.
        </p>
        <div className="space-y-2">
          {availableTools.length === 0 && (
            <p className="text-xs text-gray-500 italic">Loading tool registry&hellip;</p>
          )}
          {availableTools
            .filter((t) => !allowedToolSet || allowedToolSet.has(t.name))
            .map((t) => (
              <label
                key={t.name}
                className={`flex items-start gap-3 p-2 rounded ${readOnly ? "opacity-60 cursor-not-allowed" : "hover:bg-[#282a2c]/40 cursor-pointer"}`}
              >
                <input
                  type="checkbox"
                  checked={enabledTools.includes(t.name)}
                  onChange={() => onToggleTool(t.name)}
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
    </>
  );
}

/**
 * Same allowed-tools cap, exposed for callers that need to clamp an initial
 * `enabled_tools` array (e.g. cloning from a source workspace). Returns a
 * fresh closure each render; the work inside is cheap.
 */
export function useAllowedToolClamp(): (tools: string[]) => string[] {
  const { user } = useAuth();
  if (!user || user.is_admin) return (t: string[]) => t;
  const cap = user.allowed_tools ?? [];
  if (cap.length === 0) return (t: string[]) => t;
  const set = new Set(cap);
  return (t: string[]) => t.filter((x) => set.has(x));
}
