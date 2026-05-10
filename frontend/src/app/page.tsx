"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar"; 
import ActiveSession from "@/components/ActiveSession";
import { ChatProvider } from "@/context/ChatContext";

export default function Home() {
  const [isMounted, setIsMounted] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  useEffect(() => {
    setIsMounted(true);
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  }, []);

  if (!isMounted) return <div className="h-screen w-full bg-[#131314]" />;

  return (
    <ChatProvider>
      <div className="flex h-screen w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
        
        <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />
        
        <ActiveSession isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} />
        
      </div>
    </ChatProvider>
  );
}