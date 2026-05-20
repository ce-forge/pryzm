"use client";

import { ReactNode, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { AppProviders } from "@/context/AppProviders";

const TABS = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/workspaces", label: "Workspaces" },
  { href: "/admin/system", label: "System" },
  { href: "/admin/engine", label: "Engine" },
  { href: "/admin/audit", label: "Audit" },
  { href: "/admin/bug-reports", label: "Alerts" },
];

function AdminShell({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && (!user || !user.is_admin)) {
      router.replace("/");
    }
  }, [user, isLoading, router]);

  if (isLoading || !user || !user.is_admin) {
    return <div className="h-dvh w-full bg-[#131314]" />;
  }

  return (
    <div className="h-dvh w-full bg-[#131314] text-[#e3e3e3] flex flex-col">
      <header className="flex items-center justify-between px-6 py-4 border-b border-[#2a2a2c]">
        <h1 className="text-lg font-semibold">Admin dashboard</h1>
        <Link
          href="/"
          className="text-xs text-gray-400 hover:text-[#e3e3e3]"
        >
          Back to chat
        </Link>
      </header>

      <nav
        className="flex gap-1 px-4 border-b border-[#2a2a2c] overflow-x-auto custom-scrollbar"
        aria-label="Admin sections"
      >
        {TABS.map((tab) => {
          const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={
                "px-4 py-3 text-sm border-b-2 whitespace-nowrap transition-colors " +
                (active
                  ? "border-[#e3e3e3] text-[#e3e3e3]"
                  : "border-transparent text-gray-400 hover:text-[#e3e3e3]")
              }
              aria-current={active ? "page" : undefined}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <main className="flex-1 overflow-y-auto custom-scrollbar p-4 sm:p-6">
        {children}
      </main>
    </div>
  );
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AppProviders>
      <AdminShell>{children}</AdminShell>
    </AppProviders>
  );
}
