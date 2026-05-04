"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";

interface SessionInfo {
  id: string;
  title: string;
}

export default function Sidebar() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const searchParams = useSearchParams();
  const router = useRouter();
  
  const currentSessionId = searchParams.get("session");
  const workspace = searchParams.get("workspace") || "it_copilot";
  
  const isIT = workspace === "it_copilot";

  useEffect(() => {
    fetch(`http://127.0.0.1:8000/sessions?workspace=${workspace}`)
      .then((res) => res.json())
      .then((data) => setSessions(data))
      .catch((err) => console.error("Error loading sessions:", err));
  },[currentSessionId, workspace]);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    if (!confirm("Delete this log?")) return;
    
    try {
      const res = await fetch(`http://127.0.0.1:8000/sessions/${id}`, { method: "DELETE" });
      if (res.ok) {
        setSessions((prev) => prev.filter((s) => s.id !== id));
        if (currentSessionId === id) {
          router.push(`/?workspace=${workspace}`); 
        }
      }
    } catch (err) {
      console.error("Failed to delete", err);
    }
  };

  return (
    <div className={`w-64 border-r flex flex-col h-screen shrink-0 shadow-xl transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-950 border-slate-800' : 'bg-stone-950 border-stone-800'}`}>
      
      <div className={`p-4 border-b space-y-4 transition-colors duration-500 ease-in-out ${isIT ? 'border-slate-800' : 'border-stone-800'}`}>
        
        <div className={`flex rounded-lg p-1 border transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-900 border-slate-800' : 'bg-stone-900 border-stone-800'}`}>
          <Link 
            href="?workspace=it_copilot" 
            className={`flex-1 text-center py-1.5 text-xs font-bold rounded-md transition-all duration-500 ease-in-out ${isIT ? 'bg-slate-700 text-blue-400 shadow' : 'text-stone-500 hover:text-stone-300'}`}
          >
            IT Copilot
          </Link>
          <Link 
            href="?workspace=personal" 
            className={`flex-1 text-center py-1.5 text-xs font-bold rounded-md transition-all duration-500 ease-in-out ${!isIT ? 'bg-stone-700 text-orange-400 shadow' : 'text-slate-500 hover:text-slate-300'}`}
          >
            Personal
          </Link>
        </div>

        <Link 
          href={`/?workspace=${workspace}`} 
          className={`flex items-center justify-center w-full py-2 px-4 text-white rounded-md font-semibold shadow-lg transition-colors duration-500 ease-in-out ${isIT ? 'bg-blue-600 hover:bg-blue-500' : 'bg-orange-600 hover:bg-orange-500'}`}
        >
          + New {isIT ? 'Diagnostic' : 'Chat'}
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-1 custom-scrollbar">
        <h3 className={`text-xs font-bold uppercase tracking-wider mb-3 px-2 mt-2 transition-colors duration-500 ${isIT ? 'text-slate-500' : 'text-stone-500'}`}>
          {isIT ? 'Terminal Logs' : 'Conversations'}
        </h3>
        
        {sessions.length === 0 ? (
          <div className="text-xs text-slate-600 px-2 italic">No logs found.</div>
        ) : (
          sessions.map((s) => (
            <div 
              key={s.id} 
              className={`group flex justify-between items-center px-3 py-2 rounded-md text-sm transition-colors duration-500 ease-in-out ${
                currentSessionId === s.id 
                  ? (isIT ? "bg-slate-800 text-blue-400 border border-slate-700" : "bg-stone-800 text-orange-400 border border-stone-700")
                  : (isIT ? "text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent" : "text-stone-400 hover:bg-stone-800 hover:text-stone-200 border border-transparent")
              }`}
            >
              <Link href={`/?workspace=${workspace}&session=${s.id}`} className="truncate flex-1">
                {s.title}
              </Link>
              <button 
                onClick={(e) => handleDelete(e, s.id)}
                className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-opacity ml-2"
                title="Delete Session"
              >✕</button>
            </div>
          ))
        )}
      </div>
      
      <div className={`p-3 border-t space-y-1 transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-900/50 border-slate-800' : 'bg-stone-900/50 border-stone-800'}`}>
        <h3 className={`text-xs font-bold uppercase tracking-wider mb-2 px-2 transition-colors duration-500 ${isIT ? 'text-slate-500' : 'text-stone-500'}`}>System Overview</h3>
        <Link href="/analytics" className={`block px-3 py-2 rounded-md text-sm transition-colors duration-500 ease-in-out ${isIT ? 'text-slate-400 hover:bg-slate-800 hover:text-blue-400' : 'text-stone-400 hover:bg-stone-800 hover:text-orange-400'}`}>📊 Analytics & Metrics</Link>
        <Link href="/integrations" className={`block px-3 py-2 rounded-md text-sm transition-colors duration-500 ease-in-out ${isIT ? 'text-slate-400 hover:bg-slate-800 hover:text-blue-400' : 'text-stone-400 hover:bg-stone-800 hover:text-orange-400'}`}>🔌 API Integrations</Link>
        <Link href="/settings" className={`block px-3 py-2 rounded-md text-sm transition-colors duration-500 ease-in-out ${isIT ? 'text-slate-400 hover:bg-slate-800 hover:text-blue-400' : 'text-stone-400 hover:bg-stone-800 hover:text-orange-400'}`}>⚙️ Settings</Link>
      </div>

      <div className={`p-4 border-t text-xs flex justify-between items-center transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-950 border-slate-800 text-slate-500' : 'bg-stone-950 border-stone-800 text-stone-500'}`}>
        <span>System Status</span>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-emerald-400 font-medium">Online</span>
        </div>
      </div>
    </div>
  );
}