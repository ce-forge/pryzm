"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import SettingsModal from "./Settings";
import SessionItem from "./SessionItem";

interface SessionInfo {
  id: string;
  title: string;
  folder_id?: string | null; 
  is_pinned?: boolean;
}

interface FolderInfo {
  id: string;
  name: string;
  isOpen: boolean;
}

interface SidebarProps {
  isOpen: boolean;
  setIsOpen: (val: boolean) => void;
  selectedModel: string;
  setSelectedModel: (model: string) => void;
  streamingSessionIdsRef: React.MutableRefObject<Set<string>>;
}

export default function Sidebar({ isOpen, setIsOpen, streamingSessionIdsRef }: SidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  
  const [folders, setFolders] = useState<FolderInfo[]>([]);
  const [editingFolderId, setEditingFolderId] = useState<string | null>(null);
  const [editFolderTitle, setEditFolderTitle] = useState("");
  const[foldersLoaded, setFoldersLoaded] = useState(false);
  
  const[isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const [dragTarget, setDragTarget] = useState<string | null>(null);
  
  const searchParams = useSearchParams();
  const router = useRouter();
  
  const currentSessionId = searchParams.get("session");
  const workspace = searchParams.get("workspace") || "it_copilot";
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  useEffect(() => {
    if (foldersLoaded) {
      const openFolders = folders.filter(f => f.isOpen).map(f => f.id);
      localStorage.setItem(`pryzm_folders_open_${workspace}`, JSON.stringify(openFolders));
    }
  }, [folders, foldersLoaded, workspace]);

  useEffect(() => {
    const handleClickOutside = () => {
      if (activeDropdown !== null) {
        setActiveDropdown(null);
      }
    };
    
    document.addEventListener("click", handleClickOutside);
    
    return () => document.removeEventListener("click", handleClickOutside);
  }, [activeDropdown]);

  const fetchSessions = () => {
    fetch(`${API_URL}/sessions?workspace=${workspace}`, { cache: 'no-store' })
      .then((res) => res.json())
      .then((data) => setSessions(data))
      .catch((err) => console.error("Error loading sessions:", err));
  };

  const fetchFolders = () => {
    fetch(`${API_URL}/folders?workspace=${workspace}`)
      .then(res => res.json())
      .then(data => {
        const savedOpen = localStorage.getItem(`pryzm_folders_open_${workspace}`);
        const openSet = savedOpen ? new Set(JSON.parse(savedOpen)) : new Set();
        setFolders(data.map((f: any) => ({ ...f, isOpen: openSet.has(f.id) })));
        setFoldersLoaded(true);
      })
      .catch(err => console.error("Error loading folders:", err));
  };

  useEffect(() => {
    fetchSessions();
    fetchFolders();
    window.addEventListener("chatCreated", fetchSessions);
    return () => window.removeEventListener("chatCreated", fetchSessions);
  },[workspace]);

  const handleDeleteSession = async (e: React.MouseEvent, id: string) => {
    e.preventDefault(); e.stopPropagation();
    if (!confirm("Delete this log?")) return;
    try {
      const res = await fetch(`${API_URL}/sessions/${id}`, { method: "DELETE" });
      if (res.ok) {
        setSessions((prev) => prev.filter((s) => s.id !== id));
        if (currentSessionId === id) router.push(`/?workspace=${workspace}`); 
      }
    } catch (err) {}
  };

  const handleRenameSessionSubmit = async (e: React.FormEvent, id: string) => {
    e.preventDefault();
    if (!editTitle.trim()) return setEditingId(null);
    setSessions((prev) => prev.map((s) => s.id === id ? { ...s, title: editTitle } : s));
    setEditingId(null);
    try {
      await fetch(`${API_URL}/sessions/${id}`, { 
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: editTitle })
      });
    } catch (err) {}
  };

  const togglePin = async (e: React.MouseEvent, id: string, currentPinned: boolean) => {
    e.stopPropagation();
    const newStatus = !currentPinned;
    setSessions(prev => prev.map(s => s.id === id ? { ...s, is_pinned: newStatus } : s));
    setActiveDropdown(null);
    try {
      await fetch(`${API_URL}/sessions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_pinned: newStatus })
      });
    } catch (err) {}
  };

  const handleDragOverSafe = (e: React.DragEvent, target: string | null) => {
    if (e.dataTransfer.types.includes("application/x-pryzm-session")) {
      e.preventDefault();
      setDragTarget(target);
    }
  };

  const handleDropToFolder = async (e: React.DragEvent, folderId: string | null) => {
    e.preventDefault();
    const sessionId = e.dataTransfer.getData("application/x-pryzm-session");
    if (!sessionId) return;
    setSessions((prev) => prev.map(s => s.id === sessionId ? { ...s, folder_id: folderId } : s));
    try {
      await fetch(`${API_URL}/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_id: folderId })
      });
    } catch (err) {}
  };

  const handleCreateFolder = async () => {
    const name = prompt("Enter new folder name:");
    if (name && name.trim()) {
      const newFolder = { id: Date.now().toString(), name: name.trim(), workspace };
      setFolders([{ ...newFolder, isOpen: true }, ...folders]);
      await fetch(`${API_URL}/folders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newFolder)
      });
    }
  };

  const handleRenameFolderSubmit = async (e: React.FormEvent, id: string) => {
    e.preventDefault();
    if (!editFolderTitle.trim()) return setEditingFolderId(null);
    setFolders(prev => prev.map(f => f.id === id ? { ...f, name: editFolderTitle } : f));
    setEditingFolderId(null);
    try {
      await fetch(`${API_URL}/folders/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editFolderTitle })
      });
    } catch (err) {}
  };

  const handleDeleteFolder = async (e: React.MouseEvent, folderId: string) => {
    e.stopPropagation();
    if (!confirm("Delete this folder? Sessions inside will not be deleted but will become unsorted.")) return;
    setFolders(prev => prev.filter(f => f.id !== folderId));
    setActiveDropdown(null);
    try {
      await fetch(`${API_URL}/folders/${folderId}`, { method: "DELETE" });
      fetchSessions(); 
    } catch (err) {}
  };

  const toggleFolder = (folderId: string) => {
    setFolders(folders.map(f => f.id === folderId ? { ...f, isOpen: !f.isOpen } : f));
  };

  const getSortedSessions = (folderId: string | null) => {
    const filtered = sessions.filter(s => s.folder_id === folderId || (folderId === null && !folders.find(f => f.id === s.folder_id)));
    const pinned = filtered.filter(s => s.is_pinned);
    const unpinned = filtered.filter(s => !s.is_pinned);
    return [...pinned, ...unpinned];
  };

  if (!isOpen) return null;

  return (
    <>
      <div 
        className="fixed inset-0 bg-black/60 z-40 md:hidden backdrop-blur-sm" 
        onClick={() => setIsOpen(false)} 
      />
      <div className="fixed md:relative w-[280px] h-full bg-[#1e1f20] flex flex-col shrink-0 transition-all duration-300 border-r border-[#333537] z-50 shadow-2xl md:shadow-none">
        
        <div className="p-4 flex items-center gap-4">
          <button onClick={() => setIsOpen(false)} className="p-2 hover:bg-[#282a2c] rounded-full text-gray-400">
             <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
          </button>
        </div>

        <div className="px-4 mb-4 space-y-3">
          <div className="flex rounded-lg p-1 bg-[#131314] border border-[#333537]">
            <Link href="?workspace=it_copilot" className={`flex-1 text-center py-1.5 text-xs font-bold rounded-md transition-all ${workspace === 'it_copilot' ? 'bg-[#282a2c] text-blue-400' : 'text-gray-500 hover:text-gray-300'}`}>IT Copilot</Link>
            <Link href="?workspace=personal" className={`flex-1 text-center py-1.5 text-xs font-bold rounded-md transition-all ${workspace !== 'it_copilot' ? 'bg-[#282a2c] text-orange-400' : 'text-gray-500 hover:text-gray-300'}`}>Personal</Link>
          </div>
          <Link href={`/?workspace=${workspace}`} className="flex items-center gap-3 bg-[#282a2c] hover:bg-[#333537] text-[#e3e3e3] px-4 py-2.5 rounded-full text-sm font-medium transition-colors w-full">
             <span className="text-xl leading-none">+</span> New chat
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar px-3 space-y-2 pb-12">
           <div className="flex items-center justify-between px-3 mt-2 mb-1">
             <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">Log Directories</span>
             <button onClick={handleCreateFolder} className="text-gray-500 hover:text-[#e3e3e3] transition-colors p-1" title="New Folder">
               <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" /></svg>
             </button>
           </div>
           
           {folders.map(folder => (
             <div 
               key={folder.id} 
               className={`pt-1 pb-1 transition-all duration-200 rounded-lg border ${dragTarget === folder.id ? 'border-blue-500 bg-[#282a2c]/50' : 'border-transparent hover:border-[#333537]/50'}`}
               onDragOver={(e) => handleDragOverSafe(e, folder.id)}
               onDragLeave={(e) => { e.preventDefault(); setDragTarget(null); }}
               onDrop={(e) => { e.preventDefault(); setDragTarget(null); handleDropToFolder(e, folder.id); }}
             >
               {editingFolderId === folder.id ? (
                 <form onSubmit={(e) => handleRenameFolderSubmit(e, folder.id)} className="px-3 py-1.5">
                   <input autoFocus value={editFolderTitle} onChange={(e) => setEditFolderTitle(e.target.value)} onBlur={(e) => handleRenameFolderSubmit(e, folder.id)} className="w-full bg-[#131314] text-[#e3e3e3] text-sm px-2 py-0.5 rounded outline-none border border-blue-500/50" />
                 </form>
               ) : (
                 <div className="group flex items-center justify-between w-full text-gray-300 hover:bg-[#282a2c] rounded-lg transition-colors">
                    <button onClick={() => toggleFolder(folder.id)} className="flex-1 flex items-center gap-2 px-3 py-1.5 text-sm font-medium">
                      <svg className={`w-3.5 h-3.5 transition-transform text-gray-500 ${folder.isOpen ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                      {folder.name}
                    </button>
                    
                    <div className="flex-shrink-0 flex items-center pr-2 relative">
                      <button 
                         type="button"
                         onClick={(e) => { 
                            e.stopPropagation(); e.nativeEvent.stopImmediatePropagation();
                            setActiveDropdown(activeDropdown === `folder_${folder.id}` ? null : `folder_${folder.id}`); 
                         }}
                         className="p-1 text-gray-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity z-10"
                      >
                         <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                           <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                         </svg>
                      </button>

                      {activeDropdown === `folder_${folder.id}` && (
                         <div className="absolute right-0 top-[90%] mt-1 w-28 bg-[#282a2c] border border-[#333537] rounded-lg shadow-xl z-50 overflow-hidden flex flex-col py-1" onClick={e => e.stopPropagation()}>
                           <button onClick={(e) => { e.preventDefault(); setEditingFolderId(folder.id); setEditFolderTitle(folder.name); setActiveDropdown(null); }} className="text-left px-3 py-1.5 text-xs hover:bg-[#333537] text-gray-300">
                             Rename
                           </button>
                           <button onClick={(e) => handleDeleteFolder(e, folder.id)} className="text-left px-3 py-1.5 text-xs hover:bg-red-500/10 text-red-400">
                             Delete
                           </button>
                         </div>
                      )}
                    </div>
                 </div>
               )}
               
               {folder.isOpen && (
                 <div className="pl-6 pr-1 py-1 space-y-0.5">
                    {getSortedSessions(folder.id).length === 0 ? (
                        <div className="text-[11px] text-gray-600 italic px-2 py-1">Drag sessions here</div>
                    ) : (
                        getSortedSessions(folder.id).map((s) => (
                          <SessionItem 
                            key={s.id} s={s} workspace={workspace} currentSessionId={currentSessionId}
                            isStreaming={streamingSessionIdsRef.current.has(s.id)}
                            editingId={editingId} editTitle={editTitle} setEditTitle={setEditTitle} 
                            handleRenameSubmit={handleRenameSessionSubmit} activeDropdown={activeDropdown} 
                            setActiveDropdown={setActiveDropdown} togglePin={togglePin} handleDelete={handleDeleteSession} 
                            setEditingId={setEditingId}
                          />
                        ))
                    )}
                 </div>
               )}
             </div>
           ))}

           <div 
              className={`pt-4 pb-12 space-y-0.5 min-h-[100px] transition-all duration-200 rounded-lg border ${dragTarget === 'unsorted' ? 'border-blue-500 bg-[#282a2c]/50' : 'border-transparent'}`}
              onDragOver={(e) => handleDragOverSafe(e, 'unsorted')}
              onDragLeave={(e) => { e.preventDefault(); setDragTarget(null); }}
              onDrop={(e) => { e.preventDefault(); setDragTarget(null); handleDropToFolder(e, null); }}
           >
             <div className="text-[11px] font-bold uppercase tracking-wider text-gray-500 px-3 mb-2 pointer-events-none">Unsorted Logs</div>
             {getSortedSessions(null).map((s) => (
                <SessionItem 
                  key={s.id} s={s} workspace={workspace} currentSessionId={currentSessionId}
                  isStreaming={streamingSessionIdsRef.current.has(s.id)}
                  editingId={editingId} editTitle={editTitle} setEditTitle={setEditTitle} 
                  handleRenameSubmit={handleRenameSessionSubmit} activeDropdown={activeDropdown} 
                  setActiveDropdown={setActiveDropdown} togglePin={togglePin} handleDelete={handleDeleteSession} 
                  setEditingId={setEditingId}
                />
              ))}
             {getSortedSessions(null).length === 0 && <div className="text-xs text-gray-600 px-3 italic pointer-events-none">No unsorted logs.</div>}
           </div>
        </div>

        <div className="mt-auto p-4 border-t border-[#333537]">
          <button onClick={() => setIsSettingsOpen(true)} className="flex items-center gap-3 text-gray-400 hover:text-[#e3e3e3] transition-colors w-full px-2 py-1">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
            <span className="text-sm font-medium">Settings</span>
          </button>
        </div>
      </div>

      {isSettingsOpen && (
        <SettingsModal workspace={workspace} close={() => setIsSettingsOpen(false)} />
      )}
    </>
  );
}