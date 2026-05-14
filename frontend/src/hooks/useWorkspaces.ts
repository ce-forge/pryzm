"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

export interface Workspace {
  id: string;
  slug: string;
  display_name: string;
  system_prompt: string;
  enabled_tools: string[];
  is_builtin: boolean;
  color: string | null;
  created_at: string;
}

export interface CreatePayload {
  display_name: string;
  clone_from?: string | null;
  color?: string;
}

export interface UpdatePayload {
  display_name?: string;
  system_prompt?: string;
  enabled_tools?: string[];
  color?: string | null;
}

export interface RemoveResult {
  deleted: boolean;
  removed_sessions: number;
  removed_folders: number;
  removed_documents: number;
}

/**
 * Owns the list of workspaces + CRUD helpers. Reads once on mount; callers
 * trigger refetch after mutations. Components consume this via WorkspaceContext.
 */
export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch("/workspaces", { cache: "no-store" });
      if (r.ok) {
        setWorkspaces(await r.json());
      }
    } catch (e) {
      console.error("Failed to load workspaces", e);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const create = useCallback(async (payload: CreatePayload): Promise<Workspace | null> => {
    try {
      const r = await apiFetch("/workspaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) return null;
      const ws = await r.json();
      await refresh();
      return ws;
    } catch (e) {
      console.error("Failed to create workspace", e);
      return null;
    }
  }, [refresh]);

  const update = useCallback(async (slug: string, payload: UpdatePayload): Promise<Workspace | null> => {
    try {
      const r = await apiFetch(`/workspaces/${slug}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) return null;
      const ws = await r.json();
      await refresh();
      return ws;
    } catch (e) {
      console.error("Failed to update workspace", e);
      return null;
    }
  }, [refresh]);

  const remove = useCallback(async (slug: string): Promise<RemoveResult | null> => {
    try {
      const r = await apiFetch(`/workspaces/${slug}`, { method: "DELETE" });
      if (!r.ok) return null;
      const body = await r.json();
      await refresh();
      return body;
    } catch (e) {
      console.error("Failed to remove workspace", e);
      return null;
    }
  }, [refresh]);

  const reset = useCallback(async (slug: string): Promise<Workspace | null> => {
    try {
      const r = await apiFetch(`/workspaces/${slug}/reset`, { method: "POST" });
      if (!r.ok) return null;
      const ws = await r.json();
      await refresh();
      return ws;
    } catch (e) {
      console.error("Failed to reset workspace", e);
      return null;
    }
  }, [refresh]);

  return { workspaces, loaded, refresh, create, update, remove, reset };
}
