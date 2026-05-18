"use client";

import React, { createContext, useContext, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useWorkspaces, type Workspace } from "@/hooks/useWorkspaces";

type WorkspacesApi = ReturnType<typeof useWorkspaces>;

interface WorkspaceContextValue {
  workspacesApi: WorkspacesApi;
  workspaceSlug: string;
  activeWorkspace: Workspace | null;
  /** True when the user has no workspaces at all. Consumers render an
   *  empty state instead of trying to chat. */
  hasNoWorkspaces: boolean;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const searchParams = useSearchParams();
  const queryParamSlug = searchParams.get("workspace");
  const workspacesApi = useWorkspaces();

  const workspaceSlug = useMemo(() => {
    if (queryParamSlug) return queryParamSlug;
    // Pick the first workspace the user owns (already ordered by position
    // in useWorkspaces). Falling back to a hardcoded slug like "it_copilot"
    // breaks for users whose admin didn't seed that template.
    if (workspacesApi.workspaces.length > 0) {
      return workspacesApi.workspaces[0].slug;
    }
    return "";
  }, [queryParamSlug, workspacesApi.workspaces]);

  const activeWorkspace = useMemo<Workspace | null>(
    () => workspacesApi.workspaces.find((w) => w.slug === workspaceSlug) ?? null,
    [workspacesApi.workspaces, workspaceSlug],
  );

  const hasNoWorkspaces =
    workspacesApi.loaded && workspacesApi.workspaces.length === 0;

  const value = useMemo(
    () => ({ workspacesApi, workspaceSlug, activeWorkspace, hasNoWorkspaces }),
    [workspacesApi, workspaceSlug, activeWorkspace, hasNoWorkspaces],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspaceContext(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspaceContext must be used inside <WorkspaceProvider>");
  return ctx;
}
