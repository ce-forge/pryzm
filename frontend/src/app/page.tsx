// frontend/src/app/page.tsx
"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar"; 
import ChatUI from "@/components/ChatUi";
import { useChatLogic } from "@/hooks/useChatLogic";

export default function Home() {
  const [isMounted, setIsMounted] = useState(false);
  const[isSidebarOpen, setIsSidebarOpen] = useState(true);
  
  const chatLogic = useChatLogic();

  useEffect(() => {
    setIsMounted(true);
    if (window.innerWidth < 768) {
      setIsSidebarOpen(false);
    }
  }, []);

  if (!isMounted) return <div className="h-screen w-full bg-[#131314]" />;

  return (
    <div className="flex h-screen w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
      <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />
      <ChatUI 
        {...chatLogic} 
        isSidebarOpen={isSidebarOpen} 
        setIsSidebarOpen={setIsSidebarOpen} 
      />
    </div>
  );
}