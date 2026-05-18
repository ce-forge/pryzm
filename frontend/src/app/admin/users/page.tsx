"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

interface AdminUser {
  id: string;
  username: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  can_create_workspaces: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

const PASSWORD_MIN = 4;

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // Create form
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [canCreateWorkspaces, setCanCreateWorkspaces] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    setLoadingList(true);
    setListError(null);
    try {
      const r = await apiFetch("/api/admin/users");
      if (!r.ok) {
        setListError(`Failed to load users (${r.status})`);
        return;
      }
      const body = await r.json();
      setUsers(Array.isArray(body) ? body : []);
    } catch (e) {
      setListError(String(e));
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUsers();
  }, [loadUsers]);

  const onSubmit = async (ev: FormEvent) => {
    ev.preventDefault();
    setFormError(null);
    setFormSuccess(null);

    if (username.trim().length < 1) {
      setFormError("Username is required.");
      return;
    }
    if (password.length < PASSWORD_MIN) {
      setFormError(`Password must be at least ${PASSWORD_MIN} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      const r = await apiFetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          password,
          is_admin: isAdmin,
          can_create_workspaces: canCreateWorkspaces,
          starter_templates: [],
        }),
      });
      if (!r.ok) {
        let detail = `Failed (${r.status})`;
        try {
          const body = await r.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // body wasn't JSON; keep the status code message
        }
        setFormError(detail);
        return;
      }
      const created = await r.json();
      setFormSuccess(`Created user ${created.username}.`);
      // Reset only the secret/sensitive bits; keep the role toggles as the
      // admin probably wants to make several users of the same shape.
      setUsername("");
      setPassword("");
      await loadUsers();
    } catch (e) {
      setFormError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-4xl space-y-8">
      <div>
        <h2 className="text-xl font-semibold mb-1">Users</h2>
        <p className="text-xs text-gray-400">
          Minimal v1 — create users and view the roster. Edit / reset password
          / deactivate / delete ship in D.8.
        </p>
      </div>

      {/* Create form */}
      <section className="border border-[#2a2a2c] rounded p-5 bg-[#161617]">
        <h3 className="text-sm font-semibold mb-4">Create user</h3>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Username">
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="off"
                className="w-full bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
                placeholder="e.g. tester"
              />
            </Field>
            <Field label={`Password (min ${PASSWORD_MIN} chars)`}>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                className="w-full bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              />
            </Field>
          </div>

          <div className="flex flex-wrap gap-6">
            <Checkbox
              label="Admin"
              checked={isAdmin}
              onChange={setIsAdmin}
              hint="Can access /admin and manage other users"
            />
            <Checkbox
              label="Can create workspaces"
              checked={canCreateWorkspaces}
              onChange={setCanCreateWorkspaces}
              hint="Allowed to add new workspaces in the chat sidebar"
            />
          </div>

          {formError && (
            <div className="text-sm text-red-400">{formError}</div>
          )}
          {formSuccess && (
            <div className="text-sm text-emerald-400">{formSuccess}</div>
          )}

          <div>
            <button
              type="submit"
              disabled={submitting}
              className="text-sm px-4 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c] disabled:opacity-50"
            >
              {submitting ? "Creating…" : "Create user"}
            </button>
          </div>
        </form>
      </section>

      {/* List */}
      <section>
        <h3 className="text-sm font-semibold mb-3">All users</h3>
        {listError && (
          <div className="mb-3 text-sm text-red-400">{listError}</div>
        )}
        <div className="border border-[#2a2a2c] rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Username</th>
                <th className="px-3 py-2 font-medium w-20">Admin</th>
                <th className="px-3 py-2 font-medium w-20">Active</th>
                <th className="px-3 py-2 font-medium w-32">Can create WS</th>
                <th className="px-3 py-2 font-medium w-44">Created</th>
                <th className="px-3 py-2 font-medium w-44">Last login</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 && !loadingList && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-3 py-6 text-center text-gray-500"
                  >
                    No users yet.
                  </td>
                </tr>
              )}
              {users.map((u) => (
                <tr key={u.id} className="border-t border-[#2a2a2c]">
                  <td className="px-3 py-2">{u.username}</td>
                  <td className="px-3 py-2">{u.is_admin ? "yes" : "no"}</td>
                  <td className="px-3 py-2">{u.is_active ? "yes" : "no"}</td>
                  <td className="px-3 py-2">
                    {u.can_create_workspaces ? "yes" : "no"}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {u.created_at
                      ? new Date(u.created_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {u.last_login_at
                      ? new Date(u.last_login_at).toLocaleString()
                      : "never"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-gray-400">{label}</span>
      {children}
    </label>
  );
}

function Checkbox({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1"
      />
      <span className="flex flex-col">
        <span className="text-sm">{label}</span>
        {hint && (
          <span className="text-xs text-gray-500 max-w-xs">{hint}</span>
        )}
      </span>
    </label>
  );
}
