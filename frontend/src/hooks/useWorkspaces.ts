"use client";

import { useCallback, useEffect, useState } from "react";
import { APP_CONFIG } from "@/utils/constants";

export interface Workspace {
  id: string;
  slug: string;
  display_name: string;
  system_prompt: string;
  enabled_tools: string[];
  preferred_model: string | null;
  is_builtin: boolean;
  created_at: string;
}

export interface CreatePayload {
  display_name: string;
  clone_from?: string | null;
}

export interface UpdatePayload {
  display_name?: string;
  system_prompt?: string;
  enabled_tools?: string[];
  preferred_model?: string | null;
}

/**
 * Owns the list of workspaces + CRUD helpers. Reads once on mount; callers
 * trigger refetch after mutations. Components consume this via ChatContext.
 */
export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${APP_CONFIG.API_URL}/workspaces`, { cache: "no-store" });
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
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) return null;
    const ws = await r.json();
    await refresh();
    return ws;
  }, [refresh]);

  const update = useCallback(async (slug: string, payload: UpdatePayload): Promise<Workspace | null> => {
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces/${slug}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) return null;
    const ws = await r.json();
    await refresh();
    return ws;
  }, [refresh]);

  const remove = useCallback(async (slug: string): Promise<{ removed_sessions: number; removed_folders: number; removed_documents: number } | null> => {
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces/${slug}`, { method: "DELETE" });
    if (!r.ok) return null;
    const body = await r.json();
    await refresh();
    return body;
  }, [refresh]);

  const reset = useCallback(async (slug: string): Promise<Workspace | null> => {
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces/${slug}/reset`, { method: "POST" });
    if (!r.ok) return null;
    const ws = await r.json();
    await refresh();
    return ws;
  }, [refresh]);

  return { workspaces, loaded, refresh, create, update, remove, reset };
}
