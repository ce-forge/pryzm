"use client";

import React, { useEffect, useState } from "react";
import { useSessionMetaContext } from "@/context/SessionMetaContext";
import { useSessionList } from "@/hooks/useSessionList";
import { useFolderList, type FolderInfo } from "@/hooks/useFolderList";
import SessionItem from "./SessionItem";
import ConfirmModal from "./ConfirmModal";
import InlineCreateForm from "./InlineCreateForm";

export default function SessionDirectory() {
  const {
    workspace,
    currentSession: currentSessionId,
    streamingSessionIdsRef,
    subscribeSessionCreated,
  } = useSessionMetaContext();

  const { sessions, setSessions, fetchSessions, moveSessionToFolder } = useSessionList({
    workspace,
    currentSessionId,
    subscribeSessionCreated,
  });
  const { folders, createFolder, renameFolder, deleteFolder, toggleFolder } = useFolderList({
    workspace,
  });

  const [editingFolderId, setEditingFolderId] = useState<string | null>(null);
  const [editFolderTitle, setEditFolderTitle] = useState("");
  const [activeFolderDropdown, setActiveFolderDropdown] = useState<string | null>(null);
  const [dragTarget, setDragTarget] = useState<string | null>(null);
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [folderPendingDelete, setFolderPendingDelete] = useState<FolderInfo | null>(null);

  useEffect(() => {
    const handleClickOutside = () => setActiveFolderDropdown(null);
    document.addEventListener("click", handleClickOutside);
    return () => document.removeEventListener("click", handleClickOutside);
  }, []);

  const handleDragOverSafe = (e: React.DragEvent, target: string | null) => {
    if (e.dataTransfer.types.includes("application/x-pryzm-session")) {
      e.preventDefault();
      setDragTarget(target);
    }
  };

  const handleDropToFolder = (e: React.DragEvent, folderId: string | null) => {
    e.preventDefault();
    const sessionId = e.dataTransfer.getData("application/x-pryzm-session");
    if (!sessionId) return;
    moveSessionToFolder(sessionId, folderId);
  };

  const handleCreateFolderSubmit = async (name: string) => {
    setIsCreatingFolder(false);
    await createFolder(name);
  };

  const handleRenameFolderSubmit = async (e: React.FormEvent, id: string) => {
    e.preventDefault();
    const cleaned = editFolderTitle.trim();
    setEditingFolderId(null);
    if (!cleaned) return;
    await renameFolder(id, cleaned);
  };

  const requestDeleteFolder = (e: React.MouseEvent, folder: FolderInfo) => {
    e.preventDefault();
    e.stopPropagation();
    setActiveFolderDropdown(null);
    setFolderPendingDelete(folder);
  };

  const confirmDeleteFolder = async () => {
    if (!folderPendingDelete) return;
    const snapshot = folderPendingDelete;
    setFolderPendingDelete(null);
    await deleteFolder(snapshot);
    // Sessions inside the deleted folder become unsorted; refetch so their
    // folder_id reflects the new state.
    fetchSessions();
  };

  const getSortedSessions = (folderId: string | null) => {
    const filtered = sessions.filter(s => {
        if (folderId !== null) return s.folder_id === folderId;
        return !s.folder_id || !folders.find(f => f.id === s.folder_id);
    });

    const pinned = filtered.filter(s => s.is_pinned);
    const unpinned = filtered.filter(s => !s.is_pinned);
    return [...pinned, ...unpinned];
  };

  return (
    <>
      <div className="flex items-center justify-between px-3 mt-2 mb-1">
        <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">Log Directories</span>
        <button
          onClick={() => setIsCreatingFolder(true)}
          className="text-gray-500 hover:text-[#e3e3e3] transition-colors p-1"
          title="New Folder"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
          </svg>
        </button>
      </div>

      {isCreatingFolder && (
        <InlineCreateForm
          placeholder="Folder name"
          onSubmit={handleCreateFolderSubmit}
          onCancel={() => setIsCreatingFolder(false)}
        />
      )}

      {/* eslint-disable-next-line react-hooks/refs -- map closure reads streamingSessionIdsRef inside SessionItem props */}
      {folders.map(folder => (
        <div
          key={folder.id}
          className={`pt-1 pb-1 transition-all duration-200 rounded-lg border ${
            dragTarget === folder.id
              ? 'border-blue-500 bg-[#282a2c]/50'
              : 'border-transparent hover:border-[#4b4d4f] hover:bg-[#1a1b1c]/80 hover:shadow-sm'
          }`}
          onDragOver={(e) => handleDragOverSafe(e, folder.id)}
          onDragLeave={(e) => { e.preventDefault(); setDragTarget(null); }}
          onDrop={(e) => { e.preventDefault(); setDragTarget(null); handleDropToFolder(e, folder.id); }}
        >
          {editingFolderId === folder.id ? (
            <form onSubmit={(e) => handleRenameFolderSubmit(e, folder.id)} className="px-3 py-1.5">
              <input
                autoFocus
                value={editFolderTitle}
                onChange={(e) => setEditFolderTitle(e.target.value)}
                onBlur={(e) => handleRenameFolderSubmit(e, folder.id)}
                className="w-full bg-[#131314] text-[#e3e3e3] text-sm px-2 py-0.5 rounded outline-none border border-blue-500/50"
              />
            </form>
          ) : (
            <div className="group flex items-center justify-between w-full text-gray-300 hover:bg-[#282a2c] rounded-lg transition-colors">
              <button
                onClick={() => toggleFolder(folder.id)}
                className="flex-1 flex items-center gap-2 px-3 py-1.5 text-sm font-medium"
              >
                <svg
                  className={`w-3.5 h-3.5 transition-transform text-gray-500 ${folder.isOpen ? 'rotate-90' : ''}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                {folder.name}
              </button>

              <div className="flex-shrink-0 flex items-center pr-2 relative">
                <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      e.nativeEvent.stopImmediatePropagation();
                      setActiveFolderDropdown(activeFolderDropdown === `folder_${folder.id}` ? null : `folder_${folder.id}`);
                    }}
                    className="p-1 text-gray-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity z-10"
                >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                    </svg>
                </button>

                {activeFolderDropdown === `folder_${folder.id}` && (
                    <div
                      className="absolute right-0 top-[90%] mt-1 w-28 bg-[#282a2c] border border-[#333537] rounded-lg shadow-xl z-50 overflow-hidden flex flex-col py-1"
                      onClick={e => e.stopPropagation()}
                    >
                      <button
                        onClick={(e) => { e.preventDefault(); setEditingFolderId(folder.id); setEditFolderTitle(folder.name); setActiveFolderDropdown(null); }}
                        className="text-left px-3 py-1.5 text-xs hover:bg-[#333537] text-gray-300"
                      >
                        Rename
                      </button>
                      <button
                        onClick={(e) => requestDeleteFolder(e, folder)}
                        className="text-left px-3 py-1.5 text-xs hover:bg-red-500/10 text-red-400"
                      >
                        Delete
                      </button>
                    </div>
                )}
              </div>
            </div>
          )}

          {folder.isOpen && (
            <div className="pl-6 pr-1 py-1 space-y-0.5 max-h-[320px] overflow-y-auto custom-scrollbar">
              {getSortedSessions(folder.id).length === 0 ? (
                  <div className="text-[11px] text-gray-600 italic px-2 py-1">Drag sessions here</div>
              ) : (
                  getSortedSessions(folder.id).map((s) => (
                    <SessionItem
                      key={s.id}
                      s={s}
                      workspace={workspace}
                      currentSessionId={currentSessionId}
                      isStreaming={streamingSessionIdsRef.current.has(s.id)}
                      setSessions={setSessions}
                    />
                  ))
              )}
            </div>
          )}
        </div>
      ))}

      <div
        className={`pt-4 pb-12 space-y-0.5 min-h-[100px] transition-all duration-200 rounded-lg border ${
          dragTarget === 'unsorted'
            ? 'border-blue-500 bg-[#282a2c]/50'
            : 'border-transparent'
        }`}
        onDragOver={(e) => handleDragOverSafe(e, 'unsorted')}
        onDragLeave={(e) => { e.preventDefault(); setDragTarget(null); }}
        onDrop={(e) => { e.preventDefault(); setDragTarget(null); handleDropToFolder(e, null); }}
      >
        <div className="text-[11px] font-bold uppercase tracking-wider text-gray-500 px-3 mb-2 pointer-events-none">
          Unsorted Logs
        </div>

        {/* eslint-disable-next-line react-hooks/refs -- intentional ref read inside the map; see useSession.ts for the same pattern */}
        {getSortedSessions(null).map((s) => (
          <SessionItem
            key={s.id}
            s={s}
            workspace={workspace}
            currentSessionId={currentSessionId}
            isStreaming={streamingSessionIdsRef.current.has(s.id)}
            setSessions={setSessions}
          />
        ))}

        {getSortedSessions(null).length === 0 && (
          <div className="text-xs text-gray-600 px-3 italic pointer-events-none">
            No unsorted logs.
          </div>
        )}
      </div>

      <ConfirmModal
        isOpen={!!folderPendingDelete}
        title={`Delete folder "${folderPendingDelete?.name ?? ""}"?`}
        description="Sessions inside will not be deleted but will become unsorted."
        onConfirm={confirmDeleteFolder}
        onCancel={() => setFolderPendingDelete(null)}
      />
    </>
  );
}
