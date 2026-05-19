"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ToolPicker } from "@/components/ToolPicker";
import Identicon from "@/components/Identicon";

interface AdminWorkspace {
  id: string;
  slug: string;
  display_name: string;
  user_id: string | null;
  template_id: string | null;
  owner_can_edit: boolean;
  owner_username: string | null;
  template_display_name: string | null;
  color: string | null;
  created_at: string | null;
}

interface AdminTemplate {
  id: string;
  slug: string;
  display_name: string;
  system_prompt?: string;
  enabled_tools?: string[];
  engine_config?: Record<string, unknown>;
  color: string | null;
}

interface AdminUserRow {
  id: string;
  username: string;
}

type SubTab = "templates" | "workspaces";

export default function AdminWorkspacesPage() {
  const [subTab, setSubTab] = useState<SubTab>("workspaces");
  return (
    <div className="max-w-6xl">
      <div className="flex justify-end mb-4">
        <div className="flex gap-1 border border-[#2a2a2c] rounded p-0.5 bg-[#1e1e1f]">
          <SubTabButton
            label="All workspaces"
            active={subTab === "workspaces"}
            onClick={() => setSubTab("workspaces")}
          />
          <SubTabButton
            label="Templates"
            active={subTab === "templates"}
            onClick={() => setSubTab("templates")}
          />
        </div>
      </div>

      {subTab === "workspaces" ? <AllWorkspacesView /> : <TemplatesView />}
    </div>
  );
}

function SubTabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "text-xs px-3 py-1 rounded " +
        (active
          ? "bg-[#2a2a2c] text-[#e3e3e3]"
          : "text-gray-400 hover:text-[#e3e3e3]")
      }
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// All workspaces view
// ---------------------------------------------------------------------------

function AllWorkspacesView() {
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Filters
  const [userFilter, setUserFilter] = useState<string>("");
  const [orphanedOnly, setOrphanedOnly] = useState(false);

  // Modal state
  const [editWorkspace, setEditWorkspace] = useState<AdminWorkspace | null>(null);
  const [promoteWorkspace, setPromoteWorkspace] = useState<AdminWorkspace | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (orphanedOnly) params.set("orphaned", "true");
      else if (userFilter) params.set("user_id", userFilter);
      const r = await apiFetch(`/api/admin/workspaces?${params.toString()}`);
      if (!r.ok) {
        setError(`Failed (${r.status})`);
        return;
      }
      const body = await r.json();
      setWorkspaces(Array.isArray(body) ? body : []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [userFilter, orphanedOnly]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  useEffect(() => {
    apiFetch("/api/admin/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((body: AdminUserRow[]) =>
        setUsers(Array.isArray(body) ? body : []),
      );
  }, []);

  const orphanCount = useMemo(
    () => workspaces.filter((w) => !w.user_id).length,
    [workspaces],
  );

  const deleteWorkspace = async (w: AdminWorkspace) => {
    const ok = window.confirm(
      `Delete workspace "${w.display_name}" (slug ${w.slug})?\n\n` +
        `This cascades to its sessions, folders, and documents. Cannot be undone.`,
    );
    if (!ok) return;
    const r = await apiFetch(`/api/admin/workspaces/${w.id}`, {
      method: "DELETE",
    });
    if (!r.ok) {
      window.alert(`Delete failed (${r.status})`);
      return;
    }
    await load();
  };

  const toggleOwnerCanEdit = async (w: AdminWorkspace) => {
    const r = await apiFetch(`/api/admin/workspaces/${w.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner_can_edit: !w.owner_can_edit }),
    });
    if (!r.ok) {
      window.alert(`Update failed (${r.status})`);
      return;
    }
    await load();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Owner</span>
          <select
            value={userFilter}
            onChange={(e) => {
              setUserFilter(e.target.value);
              setOrphanedOnly(false);
            }}
            disabled={orphanedOnly}
            className="bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm min-w-44 disabled:opacity-50"
          >
            <option value="">All users</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={orphanedOnly}
            onChange={(e) => {
              setOrphanedOnly(e.target.checked);
              if (e.target.checked) setUserFilter("");
            }}
          />
          <span className="text-sm">Orphaned only</span>
          <span className="text-xs text-gray-500">(no owner)</span>
        </label>

        {orphanCount > 0 && !orphanedOnly && (
          <span className="text-xs text-amber-400">
            {orphanCount} orphaned in current view
          </span>
        )}
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="border border-[#2a2a2c] rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium w-32">Owner</th>
              <th className="px-3 py-2 font-medium w-40">Template</th>
              <th className="px-3 py-2 font-medium w-28">Owner can edit</th>
              <th className="px-3 py-2 font-medium w-44">Created</th>
              <th className="px-3 py-2 font-medium w-64">Actions</th>
            </tr>
          </thead>
          <tbody>
            {workspaces.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No workspaces match the current filters.
                </td>
              </tr>
            )}
            {workspaces.map((w) => (
              <tr key={w.id} className="border-t border-[#2a2a2c]">
                <td className="px-3 py-2">
                  <div>{w.display_name}</div>
                  <div className="font-mono text-[10px] text-gray-500">
                    {w.slug}
                  </div>
                </td>
                <td className="px-3 py-2">
                  {w.owner_username ? (
                    <span className="inline-flex items-center gap-2">
                      <Identicon seed={w.owner_username} size={20} />
                      {w.owner_username}
                    </span>
                  ) : (
                    <span className="text-amber-400">(orphan)</span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">
                  {w.template_display_name ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => toggleOwnerCanEdit(w)}
                    className={
                      "text-xs px-2 py-0.5 rounded border " +
                      (w.owner_can_edit
                        ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300"
                        : "border-[#2a2a2c] text-gray-400")
                    }
                  >
                    {w.owner_can_edit ? "yes" : "no"}
                  </button>
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">
                  {w.created_at ? (
                    <>
                      <div>{new Date(w.created_at).toLocaleDateString()}</div>
                      <div>{new Date(w.created_at).toLocaleTimeString()}</div>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1 whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => setEditWorkspace(w)}
                      className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => setPromoteWorkspace(w)}
                      className="text-xs px-2 py-0.5 rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/15"
                    >
                      Make template
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteWorkspace(w)}
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

      {editWorkspace && (
        <WorkspaceEditModal
          target={editWorkspace}
          onClose={() => setEditWorkspace(null)}
          onDone={() => {
            setEditWorkspace(null);
            load();
          }}
        />
      )}

      {promoteWorkspace && (
        <WorkspacePromoteToTemplateModal
          target={promoteWorkspace}
          onClose={() => setPromoteWorkspace(null)}
          onDone={() => setPromoteWorkspace(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Templates view (read + delete for v1; create/edit/push come later)
// ---------------------------------------------------------------------------

function TemplatesView() {
  const [templates, setTemplates] = useState<AdminTemplate[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [showCreate, setShowCreate] = useState(false);
  const [editTemplate, setEditTemplate] = useState<AdminTemplate | null>(null);
  const [pushTemplate, setPushTemplate] = useState<AdminTemplate | null>(null);
  const [instantiateTemplate, setInstantiateTemplate] = useState<AdminTemplate | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch("/api/admin/templates");
      if (!r.ok) {
        setError(`Failed (${r.status})`);
        return;
      }
      const body = await r.json();
      setTemplates(Array.isArray(body) ? body : []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  useEffect(() => {
    apiFetch("/api/admin/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((body: AdminUserRow[]) =>
        setUsers(Array.isArray(body) ? body : []),
      );
  }, []);

  const deleteTemplate = async (t: AdminTemplate) => {
    const ok = window.confirm(
      `Delete template "${t.display_name}"?\n\n` +
        `User workspaces instantiated from this template are not affected — ` +
        `their template_id is set to NULL.`,
    );
    if (!ok) return;
    const r = await apiFetch(`/api/admin/templates/${t.id}`, {
      method: "DELETE",
    });
    if (!r.ok) {
      window.alert(`Delete failed (${r.status})`);
      return;
    }
    await load();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">
          Templates seed new users&apos; starter workspaces. Push to overwrite
          settings across all instances; instantiate to add one to a specific
          user.
        </p>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="text-sm px-3 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c]"
        >
          + New template
        </button>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="border border-[#2a2a2c] rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium">Display name</th>
              <th className="px-3 py-2 font-medium w-32">Slug</th>
              <th className="px-3 py-2 font-medium w-24">Color</th>
              <th className="px-3 py-2 font-medium w-72">Actions</th>
            </tr>
          </thead>
          <tbody>
            {templates.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={4}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No templates yet.
                </td>
              </tr>
            )}
            {templates.map((t) => (
              <tr key={t.id} className="border-t border-[#2a2a2c]">
                <td className="px-3 py-2">{t.display_name}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-400">
                  {t.slug}
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">
                  {t.color ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1 whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => setEditTemplate(t)}
                      className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => setPushTemplate(t)}
                      className="text-xs px-2 py-0.5 rounded border border-sky-500/30 text-sky-300 hover:bg-sky-500/15"
                    >
                      Push
                    </button>
                    <button
                      type="button"
                      onClick={() => setInstantiateTemplate(t)}
                      className="text-xs px-2 py-0.5 rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/15"
                    >
                      Instantiate
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteTemplate(t)}
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

      {showCreate && (
        <TemplateCreateModal
          onClose={() => setShowCreate(false)}
          onDone={() => {
            setShowCreate(false);
            load();
          }}
        />
      )}

      {editTemplate && (
        <TemplateEditModal
          target={editTemplate}
          onClose={() => setEditTemplate(null)}
          onDone={() => {
            setEditTemplate(null);
            load();
          }}
        />
      )}

      {pushTemplate && (
        <TemplatePushModal
          target={pushTemplate}
          onClose={() => setPushTemplate(null)}
          onDone={() => setPushTemplate(null)}
        />
      )}

      {instantiateTemplate && (
        <TemplateInstantiateModal
          target={instantiateTemplate}
          users={users}
          onClose={() => setInstantiateTemplate(null)}
          onDone={() => setInstantiateTemplate(null)}
        />
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Template modals
// ---------------------------------------------------------------------------

const TEMPLATE_COLORS = [
  "blue", "orange", "emerald", "red", "amber", "violet", "cyan", "pink", "white",
];

function ModalShell({
  title,
  onClose,
  children,
  size = "max-w-md",
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  size?: string;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className={`bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full ${size} max-h-[85vh] overflow-hidden flex flex-col border border-[#2a2a2c]`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="overflow-y-auto custom-scrollbar">{children}</div>
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

function ColorPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      <button
        type="button"
        onClick={() => onChange(null)}
        className={
          "text-xs px-2 py-1 rounded border " +
          (value === null
            ? "bg-[#2a2a2c] border-[#3a3a3c] text-[#e3e3e3]"
            : "border-[#2a2a2c] text-gray-400")
        }
      >
        none
      </button>
      {TEMPLATE_COLORS.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={
            "text-xs px-2 py-1 rounded border " +
            (value === c
              ? "bg-[#2a2a2c] border-[#3a3a3c] text-[#e3e3e3]"
              : "border-[#2a2a2c] text-gray-400 hover:text-[#e3e3e3]")
          }
        >
          {c}
        </button>
      ))}
    </div>
  );
}

function TemplateCreateModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleTool = (name: string) => {
    setEnabledTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!slug.trim() || !displayName.trim()) {
      setError("Slug and display name are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch("/api/admin/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: slug.trim(),
          display_name: displayName.trim(),
          system_prompt: systemPrompt,
          enabled_tools: enabledTools,
          color,
        }),
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
    <ModalShell title="New template" onClose={onClose} size="max-w-lg">
      <form onSubmit={submit} className="p-5 space-y-4">
        <p className="text-xs text-gray-400">
          Slug is stable forever — it shows up in cloned-workspace URLs and in
          audit logs. Pick something short and lowercase. Everything else can
          be edited later.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Slug">
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm font-mono"
              placeholder="e.g. devops"
              autoComplete="off"
            />
          </Field>
          <Field label="Display name">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              placeholder="e.g. DevOps"
            />
          </Field>
        </div>
        <Field label="System prompt">
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={5}
            className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm resize-y font-mono"
          />
        </Field>
        <Field label="Enabled tools">
          <ToolPicker selected={enabledTools} onToggle={toggleTool} />
        </Field>
        <Field label="Color">
          <ColorPicker value={color} onChange={setColor} />
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
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function TemplateEditModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminTemplate;
  onClose: () => void;
  onDone: () => void;
}) {
  const [displayName, setDisplayName] = useState(target.display_name);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [color, setColor] = useState<string | null>(target.color ?? null);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch full template details (system_prompt isn't on the list payload).
  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/templates/${encodeURIComponent(target.id)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to load (${r.status})`);
          return;
        }
        const body = await r.json();
        setDisplayName(body.display_name ?? "");
        setSystemPrompt(body.system_prompt ?? "");
        setColor(body.color ?? null);
        setEnabledTools(
          Array.isArray(body.enabled_tools) ? body.enabled_tools : [],
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target.id]);

  const toggleTool = (name: string) => {
    setEnabledTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/admin/templates/${encodeURIComponent(target.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: displayName.trim(),
          system_prompt: systemPrompt,
          enabled_tools: enabledTools,
          color,
        }),
      });
      if (!r.ok) {
        setError(`Failed (${r.status})`);
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
    <ModalShell title={`Edit ${target.slug}`} onClose={onClose} size="max-w-lg">
      {loading ? (
        <div className="p-6 text-sm text-gray-400">Loading…</div>
      ) : (
        <form onSubmit={submit} className="p-5 space-y-4">
          <Field label="Display name">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="System prompt">
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={8}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm resize-y font-mono"
            />
          </Field>
          <Field label="Enabled tools">
            <ToolPicker selected={enabledTools} onToggle={toggleTool} />
          </Field>
          <Field label="Color">
            <ColorPicker value={color} onChange={setColor} />
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
      )}
    </ModalShell>
  );
}

function TemplatePushModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminTemplate;
  onClose: () => void;
  onDone: () => void;
}) {
  const [affectedCount, setAffectedCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [filtered, setFiltered] = useState<
    { user_id: string | null; username: string | null; dropped_tools: string[] }[]
  >([]);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/workspaces?template_id=${encodeURIComponent(target.id)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to count instances (${r.status})`);
          return;
        }
        const body = await r.json();
        setAffectedCount(Array.isArray(body) ? body.length : 0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target.id]);

  const confirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/templates/${encodeURIComponent(target.id)}/push`,
        { method: "POST" },
      );
      if (!r.ok) {
        setError(`Push failed (${r.status})`);
        return;
      }
      const body = await r.json();
      const f = Array.isArray(body.filtered) ? body.filtered : [];
      setFiltered(f);
      setDone(true);
      if (f.length === 0) {
        setTimeout(onDone, 900);
      }
      // else: stay open — admin reads the filtered list and clicks Close
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Push ${target.slug}`} onClose={onClose}>
      <div className="p-5 space-y-4 text-sm">
        {loading ? (
          <div className="text-gray-400">Counting instances…</div>
        ) : done ? (
          <div className="space-y-3">
            <div className="text-emerald-300">Push complete.</div>
            {filtered.length > 0 && (
              <div className="text-xs text-gray-300 space-y-1">
                <div>
                  Filtered tools for {filtered.length} user
                  {filtered.length === 1 ? "" : "s"} due to per-user restrictions:
                </div>
                <ul className="list-disc pl-5 space-y-0.5">
                  {filtered.map((f) => (
                    <li key={f.user_id ?? f.username ?? ""}>
                      <span className="font-mono text-[#e3e3e3]">
                        {f.username ?? "(unknown)"}
                      </span>{" "}
                      — dropped{" "}
                      <code className="font-mono text-amber-300">
                        {f.dropped_tools.join(", ")}
                      </code>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={onDone}
                  className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c] mt-2"
                >
                  Close
                </button>
              </div>
            )}
          </div>
        ) : (
          <>
            <p className="text-gray-300">
              This will overwrite the system prompt, enabled tools, color, and
              engine config on{" "}
              <strong>
                {affectedCount} workspace{affectedCount === 1 ? "" : "s"}
              </strong>{" "}
              instantiated from this template. Per-workspace customizations
              that diverge from the template will be lost.
            </p>
            {error && <div className="text-red-400">{error}</div>}
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={onClose}
                className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirm}
                disabled={submitting || affectedCount === 0}
                className="text-sm px-3 py-1.5 rounded bg-sky-500/20 border border-sky-500/40 text-sky-200 hover:bg-sky-500/30 disabled:opacity-50"
              >
                {submitting
                  ? "Pushing…"
                  : affectedCount === 0
                  ? "No instances to push"
                  : `Push to ${affectedCount}`}
              </button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  );
}

function TemplateInstantiateModal({
  target,
  users,
  onClose,
  onDone,
}: {
  target: AdminTemplate;
  users: AdminUserRow[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [userId, setUserId] = useState("");
  const [ownerCanEdit, setOwnerCanEdit] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!userId) {
      setError("Pick a target user.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/templates/${encodeURIComponent(target.id)}/instantiate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: userId,
            owner_can_edit: ownerCanEdit,
          }),
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
      setDone(true);
      setTimeout(onDone, 900);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Instantiate ${target.slug}`} onClose={onClose}>
      <form onSubmit={submit} className="p-5 space-y-4 text-sm">
        {done ? (
          <div className="text-emerald-300">Workspace created.</div>
        ) : (
          <>
            <p className="text-gray-300">
              Creates a new workspace for the chosen user, seeded from this
              template. Rejects if the user already has a workspace from this
              template (delete the existing one first to re-seed).
            </p>
            <Field label="Target user">
              <select
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              >
                <option value="">Pick a user…</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))}
              </select>
            </Field>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={ownerCanEdit}
                onChange={(e) => setOwnerCanEdit(e.target.checked)}
                className="mt-1"
              />
              <span className="flex flex-col">
                <span>Owner can edit</span>
                <span className="text-xs text-gray-500">
                  Lets the recipient change system prompt + enabled tools on
                  their copy.
                </span>
              </span>
            </label>

            {error && <div className="text-red-400">{error}</div>}

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
                className="text-sm px-3 py-1.5 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
              >
                {submitting ? "Creating…" : "Instantiate"}
              </button>
            </div>
          </>
        )}
      </form>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// All-workspaces modals: edit + promote-to-template
// ---------------------------------------------------------------------------

function WorkspaceEditModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminWorkspace;
  onClose: () => void;
  onDone: () => void;
}) {
  const [displayName, setDisplayName] = useState(target.display_name);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [color, setColor] = useState<string | null>(target.color ?? null);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [ownerCanEdit, setOwnerCanEdit] = useState<boolean>(target.owner_can_edit);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/workspaces/${encodeURIComponent(target.id)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to load (${r.status})`);
          return;
        }
        const body = await r.json();
        setDisplayName(body.display_name ?? "");
        setSystemPrompt(body.system_prompt ?? "");
        setColor(body.color ?? null);
        setEnabledTools(Array.isArray(body.enabled_tools) ? body.enabled_tools : []);
        setOwnerCanEdit(!!body.owner_can_edit);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target.id]);

  const toggleTool = (name: string) => {
    setEnabledTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/workspaces/${encodeURIComponent(target.id)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            display_name: displayName.trim(),
            system_prompt: systemPrompt,
            enabled_tools: enabledTools,
            color,
            owner_can_edit: ownerCanEdit,
          }),
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
    <ModalShell title={`Edit ${target.slug}`} onClose={onClose} size="max-w-lg">
      {loading ? (
        <div className="p-6 text-sm text-gray-400">Loading…</div>
      ) : (
        <form onSubmit={submit} className="p-5 space-y-4">
          <Field label="Display name">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="System prompt">
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={8}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm resize-y font-mono"
            />
          </Field>
          <Field label="Enabled tools">
            <ToolPicker selected={enabledTools} onToggle={toggleTool} />
          </Field>
          <Field label="Color">
            <ColorPicker value={color} onChange={setColor} />
          </Field>
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="checkbox"
              checked={ownerCanEdit}
              onChange={(e) => setOwnerCanEdit(e.target.checked)}
            />
            <span>Owner can edit</span>
          </label>

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
      )}
    </ModalShell>
  );
}

function WorkspacePromoteToTemplateModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminWorkspace;
  onClose: () => void;
  onDone: () => void;
}) {
  // Pre-fetch the workspace's settings so the new template inherits them
  // (system_prompt, enabled_tools, engine_config). slug + display_name are
  // admin-chosen; everything else comes from the source workspace.
  const [slug, setSlug] = useState(target.slug);
  const [displayName, setDisplayName] = useState(target.display_name);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [engineConfig, setEngineConfig] = useState<Record<string, unknown>>({});
  const [color, setColor] = useState<string | null>(target.color ?? null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/workspaces/${encodeURIComponent(target.id)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to load source workspace (${r.status})`);
          return;
        }
        const body = await r.json();
        setSystemPrompt(body.system_prompt ?? "");
        setEnabledTools(Array.isArray(body.enabled_tools) ? body.enabled_tools : []);
        setEngineConfig(body.engine_config ?? {});
        setColor(body.color ?? null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target.id]);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!slug.trim() || !displayName.trim()) {
      setError("Slug and display name are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch("/api/admin/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: slug.trim(),
          display_name: displayName.trim(),
          system_prompt: systemPrompt,
          enabled_tools: enabledTools,
          color,
          engine_config: engineConfig,
        }),
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
      setDone(true);
      setTimeout(onDone, 900);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Make template from ${target.slug}`} onClose={onClose} size="max-w-lg">
      {loading ? (
        <div className="p-6 text-sm text-gray-400">Loading workspace settings…</div>
      ) : done ? (
        <div className="p-5 text-sm text-emerald-300">Template created.</div>
      ) : (
        <form onSubmit={submit} className="p-5 space-y-4">
          <p className="text-xs text-gray-400">
            Creates a new template seeded from this workspace&apos;s system
            prompt, enabled tools, color, and engine config. Pick a stable
            slug — it shows up in cloned-workspace URLs and audit logs.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Slug">
              <input
                type="text"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm font-mono"
                placeholder="e.g. devops"
                autoComplete="off"
              />
            </Field>
            <Field label="Display name">
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              />
            </Field>
          </div>

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
              className="text-sm px-3 py-1.5 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
            >
              {submitting ? "Creating…" : "Create template"}
            </button>
          </div>
        </form>
      )}
    </ModalShell>
  );
}
