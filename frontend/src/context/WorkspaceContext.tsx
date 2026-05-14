"use client";

import React, { createContext, useContext, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useWorkspaces, type Workspace } from "@/hooks/useWorkspaces";
import { APP_CONFIG } from "@/utils/constants";

type WorkspacesApi = ReturnType<typeof useWorkspaces>;

interface WorkspaceContextValue {
  workspacesApi: WorkspacesApi;
  workspaceSlug: string;
  activeWorkspace: Workspace | null;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const searchParams = useSearchParams();
  const workspaceSlug =
    searchParams.get("workspace") || APP_CONFIG.DEFAULT_WORKSPACE;
  const workspacesApi = useWorkspaces();

  const activeWorkspace = useMemo<Workspace | null>(
    () => workspacesApi.workspaces.find((w) => w.slug === workspaceSlug) ?? null,
    [workspacesApi.workspaces, workspaceSlug],
  );

  const value = useMemo(
    () => ({ workspacesApi, workspaceSlug, activeWorkspace }),
    [workspacesApi, workspaceSlug, activeWorkspace],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspaceContext(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspaceContext must be used inside <WorkspaceProvider>");
  return ctx;
}
