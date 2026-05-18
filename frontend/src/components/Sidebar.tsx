"use client";

import React, { useState } from "react";
import { useSessionContext } from "@/context/SessionContext";
import SettingsModal from "./Settings";
import SessionDirectory from "./SessionDirectory";
import WorkspaceSwitcher from "./WorkspaceSwitcher";
import { MenuIcon, SettingsIcon } from "./Icons";
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
      
      {/* Outer animates transform + width. Inner stays at sidebar width so
          contents don't reflow during the desktop width collapse.
          Mobile: width stays at sidebar, slides via translate-x.
          Desktop: width also drops to 0 so chat area reclaims the space. */}
      <div className={`fixed md:relative h-full shrink-0 transition-all duration-300 z-50 overflow-hidden ${isOpen ? 'w-sidebar translate-x-0' : 'w-sidebar -translate-x-full md:w-0'}`}>
        <div className="w-sidebar h-full bg-[#1e1f20] flex flex-col border-r border-[#333537] shadow-2xl md:shadow-none">

          {/* TOP: Header Controls */}
          <div className="p-4 flex items-center gap-4">
            <button onClick={() => setIsOpen(false)} className="p-2 hover:bg-[#282a2c] rounded-full text-gray-400">
              <MenuIcon className="w-5 h-5" />
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
              <SettingsIcon className="w-5 h-5" />
              <span className="text-sm font-medium">Settings</span>
            </button>
          </div>
        </div>
      </div>

      {isSettingsOpen && <SettingsModal workspace={session.workspace} close={() => setIsSettingsOpen(false)} />}
    </>
  );
}