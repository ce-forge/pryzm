"use client";

import React from "react";
import { AuthProvider } from "@/context/AuthContext";

/**
 * Auth lives at the outermost layer so every route can read `useAuth()`
 * regardless of whether it's a chat page or an admin route. The data-
 * fetching providers (workspaces, sessions, inference, uploader, test
 * suite) live in ChatProviders and only mount once the user is known.
 */
export function AppProviders({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
