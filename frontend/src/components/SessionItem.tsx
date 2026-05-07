import React, { useRef } from "react";
import Link from "next/link";
import { useOnClickOutside } from "@/hooks/useOnClickOutside";

interface SessionItemProps {
  s: {
    id: string;
    title: string;
    is_pinned?: boolean;
  };
  workspace: string;
  currentSessionId: string | null;
  editingId: string | null;
  editTitle: string;
  setEditTitle: (val: string) => void;
  handleRenameSubmit: (e: React.FormEvent, id: string) => void;
  activeDropdown: string | null;
  setActiveDropdown: (val: string | null) => void;
  togglePin: (e: React.MouseEvent, id: string, currentPinned: boolean) => void;
  handleDelete: (e: React.MouseEvent, id: string) => void;
  setEditingId: (id: string | null) => void;
}

export default function SessionItem({
  s, workspace, currentSessionId, editingId, editTitle, setEditTitle,
  handleRenameSubmit, activeDropdown, setActiveDropdown, togglePin, handleDelete, setEditingId
}: SessionItemProps) {
  
  const dropdownRef = useRef<HTMLDivElement>(null);

  useOnClickOutside(dropdownRef, () => {
    if (activeDropdown === s.id) {
      setActiveDropdown(null);
    }
  });

  return (
    <div 
      draggable 
      onDragStart={(e) => e.dataTransfer.setData("application/x-pryzm-session", s.id)}
      className={`group flex items-center justify-between rounded-lg transition-colors cursor-grab active:cursor-grabbing ${currentSessionId === s.id ? 'bg-[#282a2c] text-[#e3e3e3]' : 'text-gray-400 hover:bg-[#282a2c] hover:text-[#e3e3e3]'}`}
    >
      {editingId === s.id ? (
        <form onSubmit={(e) => handleRenameSubmit(e, s.id)} className="flex-1 px-3 py-1.5">
          <input 
            autoFocus 
            value={editTitle} 
            onChange={(e) => setEditTitle(e.target.value)} 
            onBlur={(e) => handleRenameSubmit(e, s.id)} 
            className="w-full bg-[#131314] text-[#e3e3e3] text-sm px-2 py-0.5 rounded outline-none border border-blue-500/50" 
          />
        </form>
      ) : (
        <Link href={`/?workspace=${workspace}&session=${s.id}`} className="truncate flex-1 min-w-0 px-3 py-2 text-sm">
           {s.title}
        </Link>
      )}
      
      {editingId !== s.id && (
        <div className="flex-shrink-0 flex items-center pr-2 relative" ref={dropdownRef}>
          {s.is_pinned && (
             <svg 
               className="w-3 h-3 text-gray-500 mr-1.5 opacity-70" 
               fill="currentColor" 
               viewBox="0 0 24 24" 
             >
               <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6l.8 1.2.8-1.2v-6H19v-2l-2-2z" />
             </svg>
          )}
          
          <button 
             type="button"
             onClick={(e) => { 
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
                setActiveDropdown(activeDropdown === s.id ? null : s.id); 
             }}
             className="p-1 text-gray-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity z-10"
          >
             <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
               <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
             </svg>
          </button>

          {activeDropdown === s.id && (
             <div className="absolute right-0 top-[90%] mt-1 w-28 bg-[#282a2c] border border-[#333537] rounded-lg shadow-xl z-50 overflow-hidden flex flex-col py-1" onClick={e => e.stopPropagation()}>
               <button onClick={(e) => togglePin(e, s.id, !!s.is_pinned)} className="text-left px-3 py-1.5 text-xs hover:bg-[#333537] text-gray-300">
                 {s.is_pinned ? "Unpin" : "Pin to Top"}
               </button>
               <button onClick={(e) => { 
                 e.preventDefault();
                 setEditingId(s.id); 
                 setEditTitle(s.title); 
                 setActiveDropdown(null); 
               }} className="text-left px-3 py-1.5 text-xs hover:bg-[#333537] text-gray-300">
                 Rename
               </button>
               <button onClick={(e) => { 
                 setActiveDropdown(null);
                 handleDelete(e, s.id); 
               }} className="text-left px-3 py-1.5 text-xs hover:bg-red-500/10 text-red-400">
                 Delete
               </button>
             </div>
          )}
        </div>
      )}
    </div>
  );
}