"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import ActiveSession from "@/components/ActiveSession";
import { AppProviders } from "@/context/AppProviders";
import { LoginPage } from "@/components/LoginPage";
import ChangePasswordForm from "@/components/ChangePasswordForm";
import { useAuth } from "@/context/AuthContext";

function AppShell() {
  const { user, isLoading, refresh } = useAuth();
  const [isMounted, setIsMounted] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsMounted(true);
    if (typeof window !== "undefined" && window.innerWidth < 768) setIsSidebarOpen(false);
  }, []);

  if (!isMounted || isLoading) {
    return <div className="h-dvh w-full bg-[#131314]" />;
  }

  if (!user) {
    return <LoginPage />;
  }

  if (user.must_change_password) {
    return (
      <div className="flex h-dvh w-full items-center justify-center bg-[#131314] text-[#e3e3e3]">
        <div className="w-full max-w-sm p-8">
          <h1 className="text-xl font-semibold mb-4">Set your password</h1>
          <ChangePasswordForm forcedMode onSuccess={refresh} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-dvh w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
      <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />
      <ActiveSession isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} />
    </div>
  );
}

export default function Home() {
  return (
    <AppProviders>
      <AppShell />
    </AppProviders>
  );
}
