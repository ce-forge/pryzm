"use client";

import React, { useState } from "react";
import { useSessionContext } from "@/context/SessionContext";
import SettingsModal from "./Settings";
import SessionDirectory from "./SessionDirectory";
import WorkspaceSwitcher from "./WorkspaceSwitcher";
import { markSidebarScrolling } from "@/hooks/useSidebarPrefetchGuard";

interface SidebarProps {
  isOpen: boolean;
  setIsOpen: (val: boolean) => void;
}

export default function Sidebar({ isOpen, setIsOpen }: SidebarProps) {
  const session = useSessionContext();
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 md:hidden backdrop-blur-sm"
          onClick={() => setIsOpen(false)}
        />
      )}
      
      {/* Outer animates width/position; inner stays 280px so contents
          don't reflow during the desktop collapse animation. */}
      <div className={`fixed md:relative h-full shrink-0 transition-all duration-300 z-50 overflow-hidden w-[280px] ${isOpen ? 'left-0 md:w-[280px]' : '-left-[280px] md:left-0 md:w-0'}`}>
        <div className="w-[280px] h-full bg-[#1e1f20] flex flex-col border-r border-[#333537] shadow-2xl md:shadow-none">

          {/* TOP: Header Controls */}
          <div className="p-4 flex items-center gap-4">
            <button onClick={() => setIsOpen(false)} className="p-2 hover:bg-[#282a2c] rounded-full text-gray-400">
               <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
            </button>
          </div>

          {/* TOP: Workspace Switcher & New Chat */}
          <WorkspaceSwitcher />
          <div className="px-4 mb-4">
            <button
               onClick={() => session.navigateToSession("")}
               className="flex items-center justify-center gap-3 bg-[#282a2c] hover:bg-[#333537] text-[#e3e3e3] px-4 py-2.5 rounded-full text-sm font-medium transition-colors w-full"
            >
               <span className="text-xl leading-none">+</span> New chat
            </button>
          </div>

          {/* MIDDLE: The Folder Engine */}
          <div className="flex-1 overflow-y-auto custom-scrollbar px-3 space-y-2 pb-12" onScroll={markSidebarScrolling}>
              <SessionDirectory />
          </div>

          {/* BOTTOM: Settings */}
          <div className="mt-auto p-4 border-t border-[#333537]">
            <button onClick={() => setIsSettingsOpen(true)} className="flex items-center gap-3 text-gray-400 hover:text-[#e3e3e3] transition-colors w-full px-2 py-1">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
              <span className="text-sm font-medium">Settings</span>
            </button>
          </div>
        </div>
      </div>

      {isSettingsOpen && <SettingsModal workspace={session.workspace} close={() => setIsSettingsOpen(false)} />}
    </>
  );
}