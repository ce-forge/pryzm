"use client";

import React from "react";
import { useSessionContext } from "@/context/SessionContext";
import { useAuth } from "@/context/AuthContext";
import SessionDirectory from "./SessionDirectory";
import WorkspaceSwitcher from "./WorkspaceSwitcher";
import { MenuIcon } from "./Icons";
import { markSidebarScrolling } from "@/hooks/useSidebarPrefetchGuard";

interface SidebarProps {
  isOpen: boolean;
  setIsOpen: (val: boolean) => void;
}

export default function Sidebar({ isOpen, setIsOpen }: SidebarProps) {
  const session = useSessionContext();
  const { user, logout } = useAuth();

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 md:hidden backdrop-blur-sm"
          onClick={() => setIsOpen(false)}
        />
      )}
      
      {/* Mobile: translate slides off (fixed pos = no layout impact).
          Desktop: negative margin pulls the layout left so chat reclaims
          the space. Both animate via a single property each — smooth in
          both directions. */}
      <div className={`fixed md:relative h-full shrink-0 transition-all duration-300 z-50 w-sidebar ${isOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0 sidebar-collapsed'}`}>
        <div className="w-sidebar h-full bg-[#1e1f20] flex flex-col border-r border-[#333537] shadow-2xl md:shadow-none">

          {/* TOP: Header Controls */}
          <div className="p-4 flex items-center justify-between gap-4">
            <button onClick={() => setIsOpen(false)} className="p-2 hover:bg-[#282a2c] rounded-full text-gray-400">
              <MenuIcon className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2">
              {user?.is_admin && (
                <a
                  href="/dashboard"
                  className="text-sm text-gray-400 hover:text-[#e3e3e3] transition-colors px-2 py-1"
                >
                  Dashboard
                </a>
              )}
              <button
                onClick={() => logout()}
                title={user ? `Sign out ${user.username}` : "Sign out"}
                className="text-sm text-gray-400 hover:text-[#e3e3e3] transition-colors px-2 py-1"
              >
                Sign out
              </button>
            </div>
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
        </div>
      </div>
    </>
  );
}