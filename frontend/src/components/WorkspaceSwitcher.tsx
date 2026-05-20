"use client";

import React, { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useWorkspaceContext } from "@/context/WorkspaceContext";
import { useAuth } from "@/context/AuthContext";
import { useOnClickOutside } from "@/hooks/useOnClickOutside";
import WorkspaceCreateModal from "./WorkspaceCreateModal";
import WorkspaceEditModal from "./WorkspaceEditModal";
import { Workspace } from "@/hooks/useWorkspaces";
import { getWorkspaceColorClasses } from "@/utils/workspaceColors";
import { WorkspaceSprite } from "@/utils/workspaceSprites";

type SettingsTarget =
  | { workspace: Workspace; mode: "edit" }
  | { workspace: null; mode: "create" }
  | null;

export default function WorkspaceSwitcher() {
  const { workspacesApi, activeWorkspace } = useWorkspaceContext();
  const { user } = useAuth();
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [settingsTarget, setSettingsTarget] = useState<SettingsTarget>(null);
  const ref = useRef<HTMLDivElement>(null);
  useOnClickOutside(ref, () => setIsOpen(false));

  const switchTo = (slug: string) => {
    setIsOpen(false);
    router.replace(`/?workspace=${slug}`);
  };

  // Silent redirect when the URL points at an unknown/deleted workspace slug.
  useEffect(() => {
    if (workspacesApi.loaded && !activeWorkspace && workspacesApi.workspaces.length > 0) {
      const fallback = workspacesApi.workspaces[0];
      router.replace(`/?workspace=${fallback.slug}`);
    }
  }, [workspacesApi.loaded, activeWorkspace, workspacesApi.workspaces, router]);

  return (
    <div className="px-4 mb-4 relative" ref={ref}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between bg-[#131314] border border-[#333537] rounded-lg px-3 py-2 text-sm text-[#e3e3e3] hover:bg-[#282a2c]/50 transition-colors"
      >
        <span className="flex items-center gap-2 min-w-0">
          {activeWorkspace && (
            <WorkspaceSprite
              color={activeWorkspace.color}
              className={`w-4 h-4 shrink-0 ${getWorkspaceColorClasses(activeWorkspace.color).text}`}
            />
          )}
          <span className="truncate font-medium">{activeWorkspace?.display_name ?? "Loading..."}</span>
        </span>
        <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute left-4 right-4 top-full mt-1 bg-[#1e1f20] border border-[#333537] rounded-lg shadow-2xl z-50 overflow-hidden">
          <div className="max-h-64 overflow-y-auto custom-scrollbar">
            {workspacesApi.workspaces.map((w) => (
              <div
                key={w.slug}
                className={`flex items-center justify-between pr-1 hover:bg-[#282a2c] ${
                  activeWorkspace?.slug === w.slug ? "bg-[#282a2c]/50" : ""
                }`}
              >
                <button
                  onClick={() => switchTo(w.slug)}
                  className={`flex-1 text-left px-3 py-2 text-sm ${
                    activeWorkspace?.slug === w.slug
                      ? getWorkspaceColorClasses(w.color).text
                      : "text-gray-300"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <WorkspaceSprite
                      color={w.color}
                      className={`w-4 h-4 shrink-0 ${getWorkspaceColorClasses(w.color).text}`}
                    />
                    <span className="truncate">{w.display_name}</span>
                    {w.is_builtin && (
                      <span className="text-[9px] uppercase tracking-wider text-gray-500 shrink-0">built-in</span>
                    )}
                  </span>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsOpen(false);
                    setSettingsTarget({ workspace: w, mode: "edit" });
                  }}
                  title={`Settings for ${w.display_name}`}
                  className="p-1.5 text-gray-500 hover:text-gray-300 hover:bg-[#333537] rounded transition-colors shrink-0"
                >
                  &#9881;
                </button>
              </div>
            ))}
          </div>

          {user?.can_create_workspaces && (
            <div className="border-t border-[#333537]">
              <button
                onClick={() => {
                  setIsOpen(false);
                  setSettingsTarget({ workspace: null, mode: "create" });
                }}
                className="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-[#282a2c] hover:text-[#e3e3e3]"
              >
                + New workspace
              </button>
            </div>
          )}
        </div>
      )}

      {settingsTarget && (
        settingsTarget.mode === "edit" ? (
          <WorkspaceEditModal
            workspace={settingsTarget.workspace}
            onClose={() => setSettingsTarget(null)}
          />
        ) : (
          <WorkspaceCreateModal
            onClose={() => setSettingsTarget(null)}
          />
        )
      )}
    </div>
  );
}
