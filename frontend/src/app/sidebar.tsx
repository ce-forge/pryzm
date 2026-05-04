"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

interface SessionInfo {
  id: string;
  title: string;
}

export default function Sidebar() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const searchParams = useSearchParams();
  const currentSessionId = searchParams.get("session");

  useEffect(() => {
    fetch("http://127.0.0.1:8000/sessions")
      .then((res) => res.json())
      .then((data) => setSessions(data))
      .catch((err) => console.error("Error loading sessions:", err));
  }, [currentSessionId]);

  return (
    <div className="w-64 bg-slate-950 border-r border-slate-800 flex flex-col h-screen shrink-0 shadow-xl">
      <div className="p-4 border-b border-slate-800">
        <Link 
          href="/" 
          className="flex items-center justify-center w-full py-2 px-4 bg-emerald-600 hover:bg-emerald-500 text-white rounded-md font-semibold shadow-lg transition-colors"
        >
          + New Diagnostic
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-1 custom-scrollbar">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3 px-2 mt-2">
          Terminal Logs
        </h3>
        {sessions.length === 0 ? (
          <div className="text-xs text-slate-600 px-2 italic">No logs found.</div>
        ) : (
          sessions.map((s) => (
            <Link
              key={s.id}
              href={`/?session=${s.id}`}
              className={`block px-3 py-2 rounded-md text-sm truncate transition-colors ${
                currentSessionId === s.id 
                  ? "bg-slate-800 text-emerald-400 border border-slate-700" 
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent"
              }`}
            >
              {s.title}
            </Link>
          ))
        )}
      </div>
      
      <div className="p-3 border-t border-slate-800 space-y-1 bg-slate-900/50">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 px-2">
          System Overview
        </h3>
        <Link href="/analytics" className="block px-3 py-2 rounded-md text-sm text-slate-400 hover:bg-slate-800 hover:text-emerald-400 transition-colors">
          📊 Analytics & Metrics
        </Link>
        <Link href="/integrations" className="block px-3 py-2 rounded-md text-sm text-slate-400 hover:bg-slate-800 hover:text-emerald-400 transition-colors">
          🔌 API Integrations
        </Link>
        <Link href="/settings" className="block px-3 py-2 rounded-md text-sm text-slate-400 hover:bg-slate-800 hover:text-emerald-400 transition-colors">
          ⚙️ Settings
        </Link>
      </div>

      <div className="p-4 border-t border-slate-800 text-xs text-slate-500 flex justify-between items-center bg-slate-950">
        <span>System Status</span>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-emerald-400 font-medium">Online</span>
        </div>
      </div>
    </div>
  );
}