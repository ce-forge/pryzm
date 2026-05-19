"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

export interface AuthWorkspace {
  id: string;
  slug: string;
  display_name: string;
  color: string | null;
  owner_can_edit: boolean;
  template_id: string | null;
  position: number;
}

export interface AuthUser {
  id: string;
  username: string;
  is_admin: boolean;
  can_create_workspaces: boolean;
  allowed_tools: string[];
  email: string | null;
  workspaces: AuthWorkspace[];
  must_change_password: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const r = await apiFetch("/api/auth/me");
      if (r.ok) {
        const body = (await r.json()) as AuthUser;
        setUser(body);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Network error on logout — still clear local state.
    }
    setUser(null);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, isLoading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
