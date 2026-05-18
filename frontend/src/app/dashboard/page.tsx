"use client";

import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { AppProviders } from "@/context/AppProviders";
import ChangePasswordForm from "@/components/ChangePasswordForm";

/**
 * Per-user profile page. Used to host admin-only content (Models +
 * Micro-prompts); that content moved to /admin/system in D.7 of the
 * dashboard rollout, leaving this as the universal "your account" page.
 */
function ProfilePageBody() {
  const { user, isLoading } = useAuth();

  if (isLoading || !user) {
    return <div className="h-dvh w-full bg-[#131314]" />;
  }

  return (
    <div className="h-dvh w-full bg-[#131314] text-[#e3e3e3] p-8 overflow-y-auto custom-scrollbar">
      <div className="mx-auto max-w-md space-y-6">
        <header className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Your account</h1>
          <Link
            href="/"
            className="text-xs text-gray-400 hover:text-[#e3e3e3]"
          >
            Back to chat
          </Link>
        </header>

        <section>
          <h2 className="text-sm font-semibold mb-2 text-gray-300">
            Signed in as
          </h2>
          <div className="text-sm font-mono">{user.username}</div>
        </section>

        <section>
          <h2 className="text-sm font-semibold mb-3 text-gray-300">
            Change password
          </h2>
          <ChangePasswordForm />
        </section>

        {user.is_admin && (
          <section>
            <h2 className="text-sm font-semibold mb-2 text-gray-300">
              Admin tools
            </h2>
            <Link
              href="/admin"
              className="text-sm text-sky-400 hover:underline"
            >
              Open admin dashboard →
            </Link>
          </section>
        )}
      </div>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <AppProviders>
      <ProfilePageBody />
    </AppProviders>
  );
}
