import React from "react";
import { useChatContext } from "@/context/ChatContext";
import { getWorkspaceColorClasses } from "@/utils/workspaceColors";

interface ChatHeaderProps {
  sessionTitle: string;
  isSidebarOpen: boolean;
  setIsSidebarOpen: (val: boolean) => void;
  rightActions?: React.ReactNode;
}

export default function ChatHeader({
  sessionTitle, isSidebarOpen, setIsSidebarOpen, rightActions
}: ChatHeaderProps) {
  const { activeWorkspace } = useChatContext();
  const wsName = activeWorkspace?.display_name ?? "Pryzm";
  const wsModel = activeWorkspace?.model_name;
  const wsColorClasses = getWorkspaceColorClasses(activeWorkspace?.color);

  return (
    <header className="flex items-center justify-between p-4 shrink-0 border-b border-[#333537]/30 bg-[#131314]/80 backdrop-blur-sm z-10 sticky top-0 gap-4">
       <div className="flex items-center gap-3 flex-1 min-w-0">
          {!isSidebarOpen && (
            <button onClick={() => setIsSidebarOpen(true)} className="p-2 hover:bg-[#282a2c] rounded-lg text-gray-400 transition-colors shrink-0">
               <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
            </button>
          )}

          <div className="flex flex-col justify-center min-w-0">
            <h1 className="text-[17px] text-[#e3e3e3] font-semibold tracking-wide truncate h-[24px]">
              {sessionTitle}
            </h1>

            <div className="flex flex-row items-center gap-2 mt-0.5 min-w-0">
              <span className="text-[11px] text-gray-500 font-medium tracking-wider uppercase shrink-0">
                DaiNamik Pryzm
              </span>
              <span className={`shrink-0 inline-flex items-center px-1.5 py-[2px] rounded text-[9px] leading-none font-bold uppercase tracking-wider border ${wsColorClasses.badge}`}>
                {wsName}
              </span>
              {wsModel && (
                <span className="shrink-0 text-[10px] text-gray-500 font-mono truncate">
                  · {wsModel}
                </span>
              )}
            </div>
          </div>
       </div>
       <div className="flex items-center shrink-0">{rightActions}</div>
    </header>
  );
}
