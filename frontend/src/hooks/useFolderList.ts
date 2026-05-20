"use client";

import { useCallback, useEffect, useState } from "react";
import { v4 as uuid } from "uuid";
import { apiFetch } from "@/utils/apiClient";
import { withRollback } from "@/utils/withRollback";

export interface FolderInfo {
  id: string;
  name: string;
  isOpen: boolean;
}

interface Options {
  workspace: string;
}

/**
 * Owns the folders list for the active workspace: fetch + CRUD mutations +
 * isOpen state with localStorage persistence per workspace.
 */
export function useFolderList({ workspace }: Options) {
  const [folders, setFolders] = useState<FolderInfo[]>([]);
  const [foldersLoaded, setFoldersLoaded] = useState(false);

  const [loadedWorkspace, setLoadedWorkspace] = useState(workspace);

  useEffect(() => {
    if (foldersLoaded && loadedWorkspace === workspace) {
      const openFolders = folders.filter((f) => f.isOpen).map((f) => f.id);
      localStorage.setItem(
        `pryzm_folders_open_${workspace}`,
        JSON.stringify(openFolders),
      );
    }
  }, [folders, foldersLoaded, workspace, loadedWorkspace]);

  const fetchFolders = useCallback(() => {
    apiFetch(`/folders?workspace=${workspace}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!Array.isArray(data)) return;
        let openSet = new Set<string>();
        try {
          const savedOpen = localStorage.getItem(`pryzm_folders_open_${workspace}`);
          if (savedOpen) openSet = new Set(JSON.parse(savedOpen));
        } catch (e) {
          console.warn("Corrupted pryzm_folders_open_* in localStorage; ignoring.", e);
        }
        setFolders(
          data.map((f: { id: string; name: string }) => ({
            ...f,
            isOpen: openSet.has(f.id),
          })),
        );
        setFoldersLoaded(true);
        setLoadedWorkspace(workspace);
      })
      .catch((err) => console.error("Error loading folders:", err));
  }, [workspace]);

  useEffect(() => {
    fetchFolders();
  }, [fetchFolders]);

  const createFolder = useCallback(
    async (name: string) => {
      // tempId is the placeholder used until the server returns the real one.
      // Without the swap, drag-drop into the new folder PATCHes sessions with
      // an id no row in `folders` has, and the move fails until a fetchFolders
      // cycle replaces state with the real backend ids.
      const tempId = `temp-${uuid()}`;
      try {
        await withRollback(
          () => setFolders((prev) => [{ id: tempId, name, isOpen: true }, ...prev]),
          () => setFolders((prev) => prev.filter((f) => f.id !== tempId)),
          async () => {
            const r = await apiFetch("/folders", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ name, workspace }),
            });
            if (!r.ok) throw new Error("create failed");
            const body = await r.json().catch(() => null);
            const realId = body && typeof body.id === "string" ? body.id : null;
            if (!realId) throw new Error("create response missing id");
            setFolders((prev) =>
              prev.map((f) => (f.id === tempId ? { ...f, id: realId } : f)),
            );
          },
        );
      } catch (err) {
        console.error("Folder create failed", err);
      }
    },
    [workspace],
  );

  const renameFolder = useCallback(
    async (id: string, nextName: string) => {
      const previous = folders.find((f) => f.id === id);
      if (!previous) return;
      try {
        await withRollback(
          () =>
            setFolders((prev) =>
              prev.map((f) => (f.id === id ? { ...f, name: nextName } : f)),
            ),
          () =>
            setFolders((prev) =>
              prev.map((f) => (f.id === id ? { ...f, name: previous.name } : f)),
            ),
          async () => {
            const r = await apiFetch(`/folders/${id}?workspace=${workspace}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ name: nextName }),
            });
            if (!r.ok) throw new Error("rename failed");
          },
        );
      } catch (err) {
        console.error("Folder rename failed", err);
      }
    },
    [folders, workspace],
  );

  const deleteFolder = useCallback(
    async (folder: FolderInfo) => {
      const folderId = folder.id;
      try {
        await withRollback(
          () => setFolders((prev) => prev.filter((f) => f.id !== folderId)),
          () =>
            setFolders((prev) => [folder, ...prev.filter((f) => f.id !== folderId)]),
          async () => {
            const r = await apiFetch(`/folders/${folderId}?workspace=${workspace}`, {
              method: "DELETE",
            });
            if (!r.ok) throw new Error("delete failed");
          },
        );
      } catch (err) {
        console.error("Folder delete failed", err);
      }
    },
    [workspace],
  );

  const toggleFolder = useCallback((folderId: string) => {
    setFolders((prev) =>
      prev.map((f) => (f.id === folderId ? { ...f, isOpen: !f.isOpen } : f)),
    );
  }, []);

  return {
    folders,
    fetchFolders,
    createFolder,
    renameFolder,
    deleteFolder,
    toggleFolder,
  };
}
