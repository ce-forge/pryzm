"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Landing on /admin redirects to the Users tab as the default — that's
 * the most common entry point (admin opens the dashboard to manage users)
 * and matches the first tab in the nav so the active-state highlight is
 * consistent.
 */
export default function AdminIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/users");
  }, [router]);
  return null;
}
