import React, { useState, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useOnClickOutside } from "@/hooks/useOnClickOutside";
import { apiFetch } from "@/utils/apiClient";
import { LoadingIcon } from "./Icons";
import ConfirmModal from "./ConfirmModal"; // NEW IMPORT
import { useSessionContext } from "@/context/SessionContext";
import { isSidebarScrolling } from "@/hooks/useSidebarPrefetchGuard";

interface SessionItemProps {
  s: { id: string; title: string; is_pinned?: boolean; folder_id?: string | null };
  workspace: string;
  currentSessionId: string | null;
  isStreaming?: boolean;
  setSessions: React.Dispatch<React.SetStateAction<{ id: string; title: string; folder_id?: string | null; is_pinned?: boolean }[]>>;
}

export default function SessionItem({
  s, workspace, currentSessionId, isStreaming, setSessions
}: SessionItemProps) {
  const router = useRouter();
  const session = useSessionContext();
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(s.title);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false); // Modal State

  const dropdownRef = useRef<HTMLDivElement>(null);
  useOnClickOutside(dropdownRef, () => setIsDropdownOpen(false));

  // Prefetch the session's messages on hover so the first click renders
  // without a loading spinner (the cache is already warm by the time the
  // user clicks).
  const hoverTimerRef = useRef<number | null>(null);
  const handleMouseEnter = () => {
    if (hoverTimerRef.current) window.clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = window.setTimeout(() => {
      if (isSidebarScrolling()) return;
      session.prefetchSession(s.id);
    }, 250);
  };
  const handleMouseLeave = () => {
    if (hoverTimerRef.current) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
  };

  const handleRenameSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editTitle.trim()) {
        setIsEditing(false);
        return setEditTitle(s.title);
    }

    setSessions(prev => prev.map(item => item.id === s.id ? { ...item, title: editTitle } : item));
    setIsEditing(false);

    try {
      await apiFetch(`/sessions/${s.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: editTitle })
      });
    } catch (err) { console.error("Rename failed", err); }
  };

  const togglePin = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const newStatus = !s.is_pinned;

    setSessions(prev => prev.map(item => item.id === s.id ? { ...item, is_pinned: newStatus } : item));
    setIsDropdownOpen(false);

    try {
      await apiFetch(`/sessions/${s.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_pinned: newStatus })
      });
    } catch (err) { console.error("Pin failed", err); }
  };

  // Trigger modal instead of native confirm
  const handleDeleteClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDropdownOpen(false);
    setShowDeleteModal(true);
  };

  // Perform actual deletion when modal confirms
  const confirmDelete = async () => {
    setShowDeleteModal(false);
    setSessions(prev => prev.filter(item => item.id !== s.id));
    if (currentSessionId === s.id) router.push(`/?workspace=${workspace}`);

    try {
      await apiFetch(`/sessions/${s.id}`, { method: "DELETE" });
    } catch (err) { console.error("Delete failed", err); }
  };

  const isActive = currentSessionId === s.id;
  const containerClasses = `group flex flex-col rounded-lg transition-colors mb-0.5 ${isActive ? 'bg-[#282a2c]' : 'hover:bg-[#282a2c]/50'}`;
  const linkClasses = `truncate flex-1 px-3 py-2 text-sm ${isActive ? 'text-[#e3e3e3]' : 'text-gray-400 group-hover:text-[#e3e3e3]'}`;

  return (
    <>
      <div
        // Disabled drag if modal is open to prevent UI collision
        draggable={!isDropdownOpen && !isEditing && !showDeleteModal}
        onDragStart={(e) => e.dataTransfer.setData("application/x-pryzm-session", s.id)}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className={containerClasses}
      >
        <div className="flex items-center justify-between w-full relative">
          
          {isEditing ? (
            <form onSubmit={handleRenameSubmit} className="flex-1 px-3 py-1.5">
              <input 
                autoFocus 
                value={editTitle} 
                onChange={(e) => setEditTitle(e.target.value)} 
                onBlur={handleRenameSubmit} 
                className="w-full bg-[#131314] text-[#e3e3e3] text-sm px-2 py-0.5 rounded outline-none border border-blue-500/50" 
              />
            </form>
          ) : (
            <Link href={`/?workspace=${workspace}&session=${s.id}`} className={linkClasses}>
               {s.title}
            </Link>
          )}
          
          <div className="flex items-center gap-1 pr-2 relative" ref={dropdownRef}>
              {isStreaming && <LoadingIcon className="w-3 h-3 text-gray-500 shrink-0" />}
              {s.is_pinned && (
                <svg className="w-3 h-3 text-gray-500 opacity-70" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6l.8 1.2.8-1.2v-6H19v-2l-2-2z" />
                </svg>
              )}
              
              <button 
                 type="button"
                 onClick={(e) => { e.stopPropagation(); setIsDropdownOpen(!isDropdownOpen); }}
                 className="p-1 text-gray-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
              >
                 <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                   <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                 </svg>
              </button>

              {isDropdownOpen && (
                 <div className="absolute right-0 top-full mt-1 w-28 bg-[#282a2c] border border-[#333537] rounded-lg shadow-xl z-[60] overflow-hidden flex flex-col py-1">
                   <button onClick={togglePin} className="text-left px-3 py-1.5 text-xs hover:bg-[#333537] text-gray-300">
                      {s.is_pinned ? "Unpin" : "Pin"}
                   </button>
                   <button onClick={() => { setIsEditing(true); setIsDropdownOpen(false); }} className="text-left px-3 py-1.5 text-xs hover:bg-[#333537] text-gray-300">
                      Rename
                 </button>
                 {/* Replaced old native call with modal trigger */}
                 <button onClick={handleDeleteClick} className="text-left px-3 py-1.5 text-xs hover:bg-red-500/10 text-red-400">
                    Delete
                 </button>
                 </div>
              )}
          </div>
        </div>
      </div>

      <ConfirmModal 
        isOpen={showDeleteModal}
        title="Delete Session?"
        description="This will permanently delete this chat log."
        onConfirm={confirmDelete}
        onCancel={() => setShowDeleteModal(false)}
      />
    </>
  );
}