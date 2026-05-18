"use client";

import React from "react";
import Link from "next/link";
import { useSessionContext } from "@/context/SessionContext";
import { useAuth } from "@/context/AuthContext";
import SessionDirectory from "./SessionDirectory";
import WorkspaceSwitcher from "./WorkspaceSwitcher";
import Identicon from "./Identicon";
import { MenuIcon, DashboardIcon, SignOutIcon } from "./Icons";
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
          <div className="p-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <button
                onClick={() => setIsOpen(false)}
                className="text-gray-400 hover:text-[#e3e3e3] transition-colors shrink-0"
                aria-label="Toggle sidebar"
              >
                <MenuIcon className="w-5 h-5" />
              </button>
              {user && (
                <div className="flex items-center gap-2 min-w-0">
                  <Identicon seed={user.username} size={24} />
                  <span className="text-sm text-gray-300 truncate">{user.username}</span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-1 shrink-0">
              {user?.is_admin && (
                <Link
                  href="/admin"
                  className="p-1.5 rounded text-gray-400 hover:text-[#e3e3e3] hover:bg-[#282a2c] transition-colors"
                  title="Dashboard"
                  aria-label="Open admin dashboard"
                >
                  <DashboardIcon className="w-4 h-4" />
                </Link>
              )}
              <button
                onClick={() => { void logout(); }}
                className="p-1.5 rounded text-gray-400 hover:text-[#e3e3e3] hover:bg-[#282a2c] transition-colors"
                title={user ? `Sign out ${user.username}` : "Sign out"}
                aria-label="Sign out"
              >
                <SignOutIcon className="w-4 h-4" />
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