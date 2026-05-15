"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import ActiveSession from "@/components/ActiveSession";
import { AppProviders } from "@/context/AppProviders";
import { TokenGate } from "@/components/TokenGate";
import { getToken } from "@/utils/apiClient";

export default function Home() {
  const [isMounted, setIsMounted] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [hasToken, setHasToken] = useState<boolean | null>(null);

  // SSR-safe hydration: localStorage and window.innerWidth are only
  // available client-side. The setState here flips the page from the
  // server-rendered placeholder to the real shell once mounted.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsMounted(true);
    setHasToken(!!getToken());
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  }, []);

  if (!isMounted || hasToken === null) {
    return <div className="h-dvh w-full bg-[#131314]" />;
  }

  if (!hasToken) {
    return <TokenGate onConfigured={() => setHasToken(true)} />;
  }

  return (
    <AppProviders>
      <div className="flex h-dvh w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
        <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />
        <ActiveSession isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} />
      </div>
    </AppProviders>
  );
}
