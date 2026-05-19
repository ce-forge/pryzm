"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { StatsPanel } from "@/components/admin/StatsPanel";
import { CreateUserForm } from "@/components/admin/users/CreateUserForm";
import { UsersListTable } from "@/components/admin/users/UsersListTable";
import { ResetPasswordModal } from "@/components/admin/users/ResetPasswordModal";
import { EditUserModal } from "@/components/admin/users/EditUserModal";
import { DeleteUserModal } from "@/components/admin/users/DeleteUserModal";
import type { AdminUser } from "@/components/admin/users/types";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

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

  const toggleActive = useCallback(
    async (u: AdminUser) => {
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
    },
    [loadUsers],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUsers();
  }, [loadUsers]);

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

        <CreateUserForm onCreated={loadUsers} />

        <UsersListTable
          users={users}
          loading={loadingList}
          error={listError}
          onEdit={setEditForUser}
          onResetPw={setResetForUser}
          onToggleActive={toggleActive}
          onDelete={setDeleteForUser}
        />

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
