"use client";

import Link from "next/link";
import Identicon from "@/components/Identicon";
import type { AdminUser } from "./types";

export function UsersListTable({
  users,
  loading,
  error,
  onEdit,
  onResetPw,
  onToggleActive,
  onDelete,
}: {
  users: AdminUser[];
  loading: boolean;
  error: string | null;
  onEdit: (u: AdminUser) => void;
  onResetPw: (u: AdminUser) => void;
  onToggleActive: (u: AdminUser) => void;
  onDelete: (u: AdminUser) => void;
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold mb-3">All users</h3>
      {error && <div className="mb-3 text-sm text-red-400">{error}</div>}
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
            {users.length === 0 && !loading && (
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
                      onClick={() => onEdit(u)}
                      className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => onResetPw(u)}
                      className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                    >
                      Reset pw
                    </button>
                    <button
                      type="button"
                      onClick={() => onToggleActive(u)}
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
                      onClick={() => onDelete(u)}
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
  );
}
