"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar"; 
import ActiveSession from "@/components/ActiveSession";
import { ChatProvider, useChatContext } from "@/context/ChatContext";

// Inner component to access context
function ChatDashboard() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const { session, selectedModel, setSelectedModel } = useChatContext();

  useEffect(() => {
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  }, []);

  return (
    <div className="flex h-screen w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
      <Sidebar 
        isOpen={isSidebarOpen} 
        setIsOpen={setIsSidebarOpen} 
        selectedModel={selectedModel}
        setSelectedModel={setSelectedModel}
        streamingSessionIdsRef={session.streamingSessionIdsRef}
      />
      <ActiveSession 
        isSidebarOpen={isSidebarOpen} 
        setIsSidebarOpen={setIsSidebarOpen} 
      />
    </div>
  );
}

export default function Home() {
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  if (!isMounted) return <div className="h-screen w-full bg-[#131314]" />;

  return (
    <ChatProvider>
      <ChatDashboard />
    </ChatProvider>
  );
}