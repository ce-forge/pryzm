"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ModalShell } from "@/components/admin/ModalShell";
import type { AdminTemplate } from "./types";

type RowState = "linked" | "slug_match_unlinked" | "none";
type Action = "update" | "adopt" | "create" | "skip";

interface PreviewRow {
  user_id: string;
  username: string;
  state: RowState;
  workspace_id: string | null;
  owner_can_edit: boolean | null;
  diff_fields: string[];
}

interface RowChoice {
  action: Action;
  owner_can_edit: boolean;
}

function defaultAction(state: RowState): Action {
  // Linked rows default to update (push is the whole point of this modal).
  // Adopt + create require explicit opt-in per row to avoid silent mass changes.
  if (state === "linked") return "update";
  return "skip";
}

const STATE_LABEL: Record<RowState, string> = {
  linked: "Linked",
  slug_match_unlinked: "Slug match",
  none: "No workspace",
};

const STATE_STYLE: Record<RowState, string> = {
  linked: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  slug_match_unlinked: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  none: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

function actionOptions(state: RowState): { value: Action; label: string }[] {
  switch (state) {
    case "linked":
      return [
        { value: "update", label: "Update" },
        { value: "skip", label: "Skip" },
      ];
    case "slug_match_unlinked":
      return [
        { value: "skip", label: "Skip" },
        { value: "adopt", label: "Adopt + update" },
      ];
    case "none":
      return [
        { value: "skip", label: "Skip" },
        { value: "create", label: "Create" },
      ];
  }
}

export function TemplateApplyModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminTemplate;
  onClose: () => void;
  onDone: () => void;
}) {
  const [rows, setRows] = useState<PreviewRow[] | null>(null);
  const [choices, setChoices] = useState<Record<string, RowChoice>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    outcomes: { user_id: string; action: string; dropped_tools: string[] }[];
    rejections: { user_id: string; reason: string }[];
  } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/admin/templates/${encodeURIComponent(target.id)}/preview`)
      .then(async (r) => {
        if (!r.ok) {
          setError(`Failed to load preview (${r.status})`);
          return;
        }
        const body = await r.json();
        const list: PreviewRow[] = Array.isArray(body.rows) ? body.rows : [];
        setRows(list);
        const seeded: Record<string, RowChoice> = {};
        for (const r of list) {
          seeded[r.user_id] = { action: defaultAction(r.state), owner_can_edit: false };
        }
        setChoices(seeded);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [target.id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const setAction = (user_id: string, action: Action) => {
    setChoices((c) => ({ ...c, [user_id]: { ...c[user_id], action } }));
  };

  const setOwnerCanEdit = (user_id: string, owner_can_edit: boolean) => {
    setChoices((c) => ({ ...c, [user_id]: { ...c[user_id], owner_can_edit } }));
  };

  const selectAllLinked = () => {
    if (!rows) return;
    setChoices((c) => {
      const next = { ...c };
      for (const r of rows) {
        if (r.state === "linked") next[r.user_id] = { ...next[r.user_id], action: "update" };
      }
      return next;
    });
  };

  const clearAll = () => {
    if (!rows) return;
    setChoices((c) => {
      const next = { ...c };
      for (const r of rows) next[r.user_id] = { ...next[r.user_id], action: "skip" };
      return next;
    });
  };

  const submit = async () => {
    if (!rows) return;
    const targets = rows
      .filter((r) => choices[r.user_id]?.action && choices[r.user_id].action !== "skip")
      .map((r) => ({
        user_id: r.user_id,
        action: choices[r.user_id].action,
        owner_can_edit: choices[r.user_id].owner_can_edit,
      }));
    if (targets.length === 0) {
      setError("No targets selected.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/templates/${encodeURIComponent(target.id)}/apply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ targets }),
        },
      );
      if (!r.ok) {
        let detail = `Apply failed (${r.status})`;
        try {
          const body = await r.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // body wasn't JSON
        }
        setError(detail);
        return;
      }
      const body = await r.json();
      setResult({
        outcomes: Array.isArray(body.outcomes) ? body.outcomes : [],
        rejections: Array.isArray(body.rejections) ? body.rejections : [],
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const pendingCount = rows
    ? rows.filter((r) => (choices[r.user_id]?.action ?? "skip") !== "skip").length
    : 0;

  return (
    <ModalShell title={`Push ${target.slug}`} onClose={onClose} size="max-w-3xl">
      <div className="p-5 space-y-4 text-sm">
        {loading ? (
          <div className="text-gray-400">Loading preview…</div>
        ) : result ? (
          <ApplyResultView
            result={result}
            usernameById={Object.fromEntries((rows ?? []).map((r) => [r.user_id, r.username]))}
            onClose={onDone}
          />
        ) : !rows || rows.length === 0 ? (
          <div className="text-gray-400">No users found.</div>
        ) : (
          <>
            <p className="text-gray-300 text-xs">
              Each row shows the user&apos;s current state relative to this
              template. <span className="text-sky-300">Linked</span> workspaces
              will be overwritten on update.{" "}
              <span className="text-amber-300">Slug match</span> means the user
              has a workspace with this slug but it isn&apos;t linked yet —
              adopt will link it then overwrite. Rows with no workspace can be
              created from scratch.
            </p>

            <div className="flex gap-2 text-xs">
              <button
                type="button"
                onClick={selectAllLinked}
                className="px-2 py-1 rounded border border-sky-500/30 text-sky-300 hover:bg-sky-500/15"
              >
                Update all linked
              </button>
              <button
                type="button"
                onClick={clearAll}
                className="px-2 py-1 rounded border border-[#2a2a2c] text-gray-300 hover:bg-[#2a2a2c]"
              >
                Clear
              </button>
            </div>

            <div className="border border-[#2a2a2c] rounded overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-[#1e1e1f] text-gray-400 text-left">
                  <tr>
                    <th className="px-3 py-2 font-medium">User</th>
                    <th className="px-3 py-2 font-medium">State</th>
                    <th className="px-3 py-2 font-medium">Will overwrite</th>
                    <th className="px-3 py-2 font-medium w-44">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const choice = choices[r.user_id] ?? {
                      action: defaultAction(r.state),
                      owner_can_edit: false,
                    };
                    return (
                      <tr key={r.user_id} className="border-t border-[#2a2a2c]">
                        <td className="px-3 py-2 font-mono">{r.username}</td>
                        <td className="px-3 py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded border text-[10px] ${STATE_STYLE[r.state]}`}
                          >
                            {STATE_LABEL[r.state]}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-gray-300">
                          {r.diff_fields.length === 0 ? (
                            <span className="text-gray-500">
                              {r.state === "none" ? "—" : "no changes"}
                            </span>
                          ) : (
                            r.diff_fields.map((f) => (
                              <code
                                key={f}
                                className="font-mono text-amber-300 mr-1.5"
                              >
                                {f}
                              </code>
                            ))
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-col gap-1">
                            <select
                              value={choice.action}
                              onChange={(e) =>
                                setAction(r.user_id, e.target.value as Action)
                              }
                              className="bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1 text-xs"
                            >
                              {actionOptions(r.state).map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>
                            {choice.action === "create" && (
                              <label className="flex items-center gap-1 text-[10px] text-gray-400 cursor-pointer">
                                <input
                                  type="checkbox"
                                  checked={choice.owner_can_edit}
                                  onChange={(e) =>
                                    setOwnerCanEdit(r.user_id, e.target.checked)
                                  }
                                />
                                Owner can edit
                              </label>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {error && <div className="text-red-400">{error}</div>}

            <div className="flex gap-2 justify-end items-center">
              <span className="text-xs text-gray-400 mr-auto">
                {pendingCount} action{pendingCount === 1 ? "" : "s"} pending
              </span>
              <button
                type="button"
                onClick={onClose}
                className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={submitting || pendingCount === 0}
                className="text-sm px-3 py-1.5 rounded bg-sky-500/20 border border-sky-500/40 text-sky-200 hover:bg-sky-500/30 disabled:opacity-50"
              >
                {submitting ? "Applying…" : `Apply ${pendingCount}`}
              </button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  );
}

function ApplyResultView({
  result,
  usernameById,
  onClose,
}: {
  result: {
    outcomes: { user_id: string; action: string; dropped_tools: string[] }[];
    rejections: { user_id: string; reason: string }[];
  };
  usernameById: Record<string, string>;
  onClose: () => void;
}) {
  const ok = result.outcomes.length;
  const failed = result.rejections.length;
  return (
    <div className="space-y-3">
      <div className="text-emerald-300">
        Applied to {ok} workspace{ok === 1 ? "" : "s"}.
        {failed > 0 && (
          <span className="text-amber-300"> {failed} rejected.</span>
        )}
      </div>
      {result.outcomes.some((o) => o.dropped_tools.length > 0) && (
        <div className="text-xs text-gray-300 space-y-1">
          <div>Filtered tools due to per-user permission restrictions:</div>
          <ul className="list-disc pl-5 space-y-0.5">
            {result.outcomes
              .filter((o) => o.dropped_tools.length > 0)
              .map((o) => (
                <li key={o.user_id}>
                  <span className="font-mono">{usernameById[o.user_id] ?? o.user_id}</span>{" "}
                  — dropped{" "}
                  <code className="font-mono text-amber-300">
                    {o.dropped_tools.join(", ")}
                  </code>
                </li>
              ))}
          </ul>
        </div>
      )}
      {failed > 0 && (
        <div className="text-xs text-gray-300 space-y-1">
          <div>Rejections:</div>
          <ul className="list-disc pl-5 space-y-0.5">
            {result.rejections.map((r) => (
              <li key={r.user_id}>
                <span className="font-mono">{usernameById[r.user_id] ?? r.user_id}</span>{" "}
                — <span className="text-amber-300">{r.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
        >
          Close
        </button>
      </div>
    </div>
  );
}
