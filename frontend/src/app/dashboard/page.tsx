"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { AppProviders } from "@/context/AppProviders";
import ModelsSection from "@/components/SettingsModels";
import MicroPromptsSection from "@/components/MicroPromptsSection";
import ChangePasswordForm from "@/components/ChangePasswordForm";

function DashboardPageBody() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && (!user || !user.is_admin)) {
      router.replace("/");
    }
  }, [user, isLoading, router]);

  if (isLoading || !user || !user.is_admin) {
    return <div className="h-dvh w-full bg-[#131314]" />;
  }

  return (
    <div className="h-dvh w-full bg-[#131314] text-[#e3e3e3] p-8 overflow-y-auto custom-scrollbar">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Admin dashboard</h1>
          <Link href="/" className="text-xs text-gray-400 hover:text-[#e3e3e3]">Back to chat</Link>
        </header>
        <section>
          <h2 className="text-sm font-medium text-gray-300 mb-3">Models</h2>
          <ModelsSection />
        </section>
        <section>
          <h2 className="text-sm font-medium text-gray-300 mb-3">Micro-Prompts</h2>
          <MicroPromptsSection />
        </section>
        <section>
          <h2 className="text-sm font-medium text-gray-300 mb-3">Change password</h2>
          <ChangePasswordForm />
        </section>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AppProviders>
      <DashboardPageBody />
    </AppProviders>
  );
}
