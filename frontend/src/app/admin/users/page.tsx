"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/utils/apiClient";
import { ToolPicker } from "@/components/ToolPicker";
import Identicon from "@/components/Identicon";
import { StatsPanel } from "@/components/admin/StatsPanel";

interface AdminUser {
  id: string;
  username: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  can_create_workspaces: boolean;
  allowed_tools: string[];
  created_at: string | null;
  last_login_at: string | null;
}

interface WorkspaceTemplate {
  id: string;
  slug: string;
  display_name: string;
}

interface StarterTemplateSelection {
  template_id: string;
  owner_can_edit: boolean;
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
  const [allowedTools, setAllowedTools] = useState<string[]>([]);
  const [templates, setTemplates] = useState<WorkspaceTemplate[]>([]);
  const [selectedTemplates, setSelectedTemplates] = useState<
    Record<string, StarterTemplateSelection>
  >({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  // Per-row modal state — null means "not open"
  const [resetForUser, setResetForUser] = useState<AdminUser | null>(null);
  const [editForUser, setEditForUser] = useState<AdminUser | null>(null);
  const [deleteForUser, setDeleteForUser] = useState<AdminUser | null>(null);

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

  const toggleActive = useCallback(async (u: AdminUser) => {
    const r = await apiFetch(`/api/admin/users/${encodeURIComponent(u.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !u.is_active }),
    });
    if (!r.ok) {
      let detail = `Failed (${r.status})`;
      try {
        const body = await r.json();
        if (typeof body?.detail === "string") detail = body.detail;
      } catch {
        // body wasn't JSON
      }
      window.alert(detail);
      return;
    }
    await loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    apiFetch("/api/admin/templates")
      .then((r) => (r.ok ? r.json() : []))
      .then((body: WorkspaceTemplate[]) => setTemplates(Array.isArray(body) ? body : []))
      .catch(() => setTemplates([]));
  }, []);

  const toggleAllowedTool = (name: string) => {
    setAllowedTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const toggleTemplate = (id: string) => {
    setSelectedTemplates((prev) => {
      const next = { ...prev };
      if (next[id]) {
        delete next[id];
      } else {
        next[id] = { template_id: id, owner_can_edit: false };
      }
      return next;
    });
  };

  const toggleOwnerCanEdit = (id: string) => {
    setSelectedTemplates((prev) => {
      if (!prev[id]) return prev;
      return {
        ...prev,
        [id]: { ...prev[id], owner_can_edit: !prev[id].owner_can_edit },
      };
    });
  };

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
          allowed_tools: allowedTools,
          starter_templates: Object.values(selectedTemplates),
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
      const seededCount = Object.keys(selectedTemplates).length;
      setFormSuccess(
        seededCount > 0
          ? `Created ${created.username} with ${seededCount} starter workspace${seededCount === 1 ? "" : "s"}.`
          : `Created ${created.username}.`
      );
      // Reset only the secret/sensitive bits; keep the role toggles as the
      // admin probably wants to make several users of the same shape.
      setUsername("");
      setPassword("");
      setAllowedTools([]);
      setSelectedTemplates({});
      await loadUsers();
    } catch (e) {
      setFormError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const stats = {
    total: users.length,
    active: users.filter((u) => u.is_active).length,
    admins: users.filter((u) => u.is_admin).length,
    canCreate: users.filter((u) => u.can_create_workspaces).length,
  };

  return (
    <div className="flex gap-6 max-w-7xl">
      <div className="flex-1 min-w-0 space-y-8">
        <p className="text-xs text-gray-400">
        Create, edit, deactivate, reset password, delete. Click a username to
        open their detail page (workspaces, recent activity, open bug reports).
      </p>

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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Allowed tools
              </label>
              <div className="max-h-60 overflow-y-auto rounded border border-[#2a2a2c] bg-[#131314] p-2 custom-scrollbar">
                <ToolPicker selected={allowedTools} onToggle={toggleAllowedTool} />
              </div>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Starter workspaces
              </label>
              {templates.length === 0 ? (
                <div className="text-xs text-gray-500 rounded border border-[#2a2a2c] bg-[#131314] p-3">
                  No workspace templates exist yet. The new user will start with
                  no workspaces and won&apos;t be able to use the AI until they
                  create one (requires &quot;Can create workspaces&quot; checked above).
                </div>
              ) : (
                <div className="max-h-60 overflow-y-auto space-y-1.5 border border-[#2a2a2c] rounded p-3 bg-[#131314] custom-scrollbar">
                  {templates.map((t) => {
                    const selected = !!selectedTemplates[t.id];
                    return (
                      <div
                        key={t.id}
                        className="flex items-center justify-between gap-3"
                      >
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleTemplate(t.id)}
                          />
                          <span className="text-sm">{t.display_name}</span>
                          <span className="text-xs text-gray-500 font-mono">
                            {t.slug}
                          </span>
                        </label>
                        {selected && (
                          <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={selectedTemplates[t.id].owner_can_edit}
                              onChange={() => toggleOwnerCanEdit(t.id)}
                            />
                            Owner can edit
                          </label>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {formError && (
            <div className="text-sm text-red-400">{formError}</div>
          )}
          {formSuccess && (
            <div className="text-sm text-emerald-400">{formSuccess}</div>
          )}

          <div className="flex justify-end">
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
        <div className="border border-[#2a2a2c] rounded overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
              <tr>
                <th className="px-3 py-2 font-medium max-md:sticky max-md:left-0 max-md:bg-[#1e1e1f]">Username</th>
                <th className="px-3 py-2 font-medium w-20">Admin</th>
                <th className="px-3 py-2 font-medium w-20">Active</th>
                <th className="px-3 py-2 font-medium w-32">Can create WS</th>
                <th className="px-3 py-2 font-medium w-44">Created</th>
                <th className="px-3 py-2 font-medium w-44">Last login</th>
                <th className="px-3 py-2 font-medium w-72">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 && !loadingList && (
                <tr>
                  <td
                    colSpan={7}
                    className="px-3 py-6 text-center text-gray-500"
                  >
                    No users yet.
                  </td>
                </tr>
              )}
              {users.map((u) => (
                <tr key={u.id} className="border-t border-[#2a2a2c]">
                  <td className="px-3 py-2 max-md:sticky max-md:left-0 max-md:bg-[#131314]">
                    <Link
                      href={`/admin/users/${encodeURIComponent(u.id)}`}
                      className="inline-flex items-center gap-2 text-sky-400 hover:underline"
                    >
                      <Identicon seed={u.username} size={20} />
                      {u.username}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{u.is_admin ? "yes" : "no"}</td>
                  <td className="px-3 py-2">{u.is_active ? "yes" : "no"}</td>
                  <td className="px-3 py-2">
                    {u.can_create_workspaces ? "yes" : "no"}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {u.created_at ? (
                      <>
                        <div>{new Date(u.created_at).toLocaleDateString()}</div>
                        <div>{new Date(u.created_at).toLocaleTimeString()}</div>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {u.last_login_at ? (
                      <>
                        <div>{new Date(u.last_login_at).toLocaleDateString()}</div>
                        <div>{new Date(u.last_login_at).toLocaleTimeString()}</div>
                      </>
                    ) : (
                      "never"
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1 whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => setEditForUser(u)}
                        className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => setResetForUser(u)}
                        className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                      >
                        Reset pw
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleActive(u)}
                        className={
                          "text-xs px-2 py-0.5 rounded border " +
                          (u.is_active
                            ? "border-amber-500/30 text-amber-300 hover:bg-amber-500/15"
                            : "border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/15")
                        }
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteForUser(u)}
                        className="text-xs px-2 py-0.5 rounded border border-red-500/30 text-red-300 hover:bg-red-500/15"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {resetForUser && (
        <ResetPasswordModal
          target={resetForUser}
          onClose={() => setResetForUser(null)}
          onDone={() => {
            setResetForUser(null);
            loadUsers();
          }}
        />
      )}

      {editForUser && (
        <EditUserModal
          target={editForUser}
          onClose={() => setEditForUser(null)}
          onDone={() => {
            setEditForUser(null);
            loadUsers();
          }}
        />
      )}

      {deleteForUser && (
        <DeleteUserModal
          target={deleteForUser}
          onClose={() => setDeleteForUser(null)}
          onDone={() => {
            setDeleteForUser(null);
            loadUsers();
          }}
        />
      )}
      </div>

      <aside className="hidden xl:block w-72 shrink-0 space-y-4">
        <StatsPanel
          title="At a glance"
          rows={[
            { label: "Total users", value: stats.total },
            { label: "Active", value: stats.active },
            { label: "Admins", value: stats.admins },
            { label: "Can create workspaces", value: stats.canCreate },
          ]}
        />
      </aside>
    </div>
  );
}

function ResetPasswordModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (newPassword.length < PASSWORD_MIN) {
      setError(`Password must be at least ${PASSWORD_MIN} characters.`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/users/${encodeURIComponent(target.id)}/password`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: newPassword }),
        },
      );
      if (!r.ok) {
        let detail = `Failed (${r.status})`;
        try {
          const body = await r.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // body wasn't JSON
        }
        setError(detail);
        return;
      }
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full max-w-sm border border-[#2a2a2c]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <h3 className="text-sm font-semibold">
            Reset password for {target.username}
          </h3>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-4">
          <p className="text-xs text-gray-400">
            The user will be forced to pick a new password on their next
            login, and all of their existing sessions will be signed out.
          </p>

          <Field label={`New password (min ${PASSWORD_MIN} chars)`}>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              autoFocus
            />
          </Field>

          {error && <div className="text-sm text-red-400">{error}</div>}

          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="text-sm px-3 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c] disabled:opacity-50"
            >
              {submitting ? "Resetting…" : "Reset password"}
            </button>
          </div>
        </form>
      </div>
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


function EditUserModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const [username, setUsername] = useState(target.username);
  const [email, setEmail] = useState(target.email ?? "");
  const [isAdmin, setIsAdmin] = useState(target.is_admin);
  const [canCreateWorkspaces, setCanCreateWorkspaces] = useState(
    target.can_create_workspaces,
  );
  const [allowedTools, setAllowedTools] = useState<string[]>(
    target.allowed_tools ?? [],
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleAllowedTool = (name: string) => {
    setAllowedTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      // Send only fields that actually changed. PATCH treats missing keys
      // as unset, so this is enough to keep the audit's changed_fields
      // payload clean.
      const patch: Record<string, unknown> = {};
      if (username.trim() !== target.username) patch.username = username.trim();
      const normalizedEmail = email.trim() || null;
      if (normalizedEmail !== (target.email ?? null)) patch.email = normalizedEmail;
      if (isAdmin !== target.is_admin) patch.is_admin = isAdmin;
      if (canCreateWorkspaces !== target.can_create_workspaces) {
        patch.can_create_workspaces = canCreateWorkspaces;
      }
      if (
        JSON.stringify([...allowedTools].sort()) !==
        JSON.stringify([...(target.allowed_tools ?? [])].sort())
      ) {
        patch.allowed_tools = allowedTools;
      }

      if (Object.keys(patch).length === 0) {
        onClose();
        return;
      }

      const r = await apiFetch(`/api/admin/users/${encodeURIComponent(target.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        let detail = `Failed (${r.status})`;
        try {
          const body = await r.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // body wasn't JSON
        }
        setError(detail);
        return;
      }
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full max-w-md border border-[#2a2a2c]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <h3 className="text-sm font-semibold">Edit {target.username}</h3>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-4">
          <Field label="Username">
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              autoComplete="off"
            />
          </Field>

          <Field label="Email (optional)">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              autoComplete="off"
            />
          </Field>

          <div className="flex flex-wrap gap-6">
            <Checkbox
              label="Admin"
              checked={isAdmin}
              onChange={setIsAdmin}
            />
            <Checkbox
              label="Can create workspaces"
              checked={canCreateWorkspaces}
              onChange={setCanCreateWorkspaces}
            />
          </div>

          <Field label="Allowed tools">
            <div className="max-h-60 overflow-y-auto rounded border border-[#2a2a2c] bg-[#131314] p-2 custom-scrollbar">
              <ToolPicker selected={allowedTools} onToggle={toggleAllowedTool} />
            </div>
          </Field>

          {error && <div className="text-sm text-red-400">{error}</div>}

          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="text-sm px-3 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c] disabled:opacity-50"
            >
              {submitting ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


function DeleteUserModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const [hardDelete, setHardDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Hard delete requires the admin to type the username — destructive
  // cascade through sessions/folders/documents, no undo.
  const canSubmit = hardDelete ? confirmText === target.username : true;

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const url = `/api/admin/users/${encodeURIComponent(target.id)}${hardDelete ? "?hard=true" : ""}`;
      const r = await apiFetch(url, { method: "DELETE" });
      if (!r.ok) {
        let detail = `Failed (${r.status})`;
        try {
          const body = await r.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // body wasn't JSON
        }
        setError(detail);
        return;
      }
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full max-w-md border border-[#2a2a2c]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <h3 className="text-sm font-semibold">Delete {target.username}</h3>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-4">
          <p className="text-sm text-gray-300">
            By default this is a <strong>soft delete</strong> — the user is
            marked inactive and signed out everywhere. Their workspaces,
            chats, and bug reports remain intact, and you can reactivate
            them later.
          </p>

          <Checkbox
            label="Hard delete (cascades through everything)"
            hint="Removes the user row AND their workspaces, chats, folders, and documents. Audit history stays (FK SET NULL on user_id)."
            checked={hardDelete}
            onChange={(v) => {
              setHardDelete(v);
              setConfirmText("");
            }}
          />

          {hardDelete && (
            <Field label={`Type "${target.username}" to confirm`}>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm font-mono"
                autoComplete="off"
              />
            </Field>
          )}

          {error && <div className="text-sm text-red-400">{error}</div>}

          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !canSubmit}
              className={
                "text-sm px-3 py-1.5 rounded border " +
                (hardDelete
                  ? "bg-red-500/20 border-red-500/40 text-red-200 hover:bg-red-500/30 disabled:opacity-50"
                  : "bg-amber-500/15 border-amber-500/30 text-amber-200 hover:bg-amber-500/25 disabled:opacity-50")
              }
            >
              {submitting
                ? "Deleting…"
                : hardDelete
                ? "Hard delete"
                : "Soft delete"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
