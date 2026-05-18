"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Landing on /admin redirects to the Audit tab as the default. The audit
 * data is the dashboard's primary unique surface (everything else is
 * either CRUD or settings already available elsewhere), so it's the
 * highest-value first view for an admin opening the dashboard.
 */
export default function AdminIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/audit");
  }, [router]);
  return null;
}
