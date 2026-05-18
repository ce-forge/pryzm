"use client";

import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiClient";

export function LoginPage() {
  const { refresh } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (r.ok) {
        await refresh();
        return;
      }
      // Backend returns 401 with a generic message on bad credentials and on
      // disabled accounts (intentional, per the auth spec).
      setError("Invalid credentials.");
    } catch {
      setError("Couldn't reach the server. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex h-dvh w-full items-center justify-center bg-[#131314] text-[#e3e3e3]">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 p-8">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <div>
          <label htmlFor="username" className="block text-xs text-slate-400 mb-1">Username</label>
          <input
            id="username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            autoFocus
          />
        </div>
        <div>
          <label htmlFor="password" className="block text-xs text-slate-400 mb-1">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={isSubmitting || !username.trim() || !password}
          className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
