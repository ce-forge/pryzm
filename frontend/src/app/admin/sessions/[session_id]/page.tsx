"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/utils/apiClient";

interface AdminSessionMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: string | null;
  created_at: string | null;
  tool_calls: unknown[] | null;
  referenced_docs: unknown[] | null;
}

interface AdminSession {
  id: string;
  title: string;
  created_at: string | null;
  owner: { id: string; username: string } | null;
  workspace: { id: string; slug: string; display_name: string } | null;
  messages: AdminSessionMessage[];
}

export default function AdminSessionReader() {
  const params = useParams<{ session_id: string }>();
  const sessionId = params.session_id;

  const [data, setData] = useState<AdminSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/admin/sessions/${encodeURIComponent(sessionId)}`);
      if (r.status === 404) {
        setError("Session not found.");
        return;
      }
      if (!r.ok) {
        setError(`Failed to load (${r.status})`);
        return;
      }
      setData(await r.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  if (loading) {
    return <div className="text-sm text-gray-400">Loading…</div>;
  }
  if (error) {
    return <div className="text-sm text-red-400">{error}</div>;
  }
  if (!data) {
    return null;
  }

  return (
    <div className="max-w-3xl space-y-6">
      <header className="space-y-2">
        <Link
          href="/admin/audit"
          className="text-xs text-gray-400 hover:text-[#e3e3e3]"
        >
          ← Back to audit
        </Link>
        <h2 className="text-xl font-semibold">{data.title || "Untitled session"}</h2>
        <div className="flex flex-wrap gap-3 text-xs text-gray-400">
          {data.owner ? (
            <Link
              href={`/admin/users/${encodeURIComponent(data.owner.id)}`}
              className="hover:text-[#e3e3e3]"
            >
              Owner: {data.owner.username}
            </Link>
          ) : (
            <span>Owner: (deleted)</span>
          )}
          {data.workspace ? (
            <span>
              Workspace: {data.workspace.display_name}{" "}
              <span className="font-mono text-gray-500">
                ({data.workspace.slug})
              </span>
            </span>
          ) : (
            <span>Workspace: (deleted)</span>
          )}
          {data.created_at && (
            <span>Created: {new Date(data.created_at).toLocaleString()}</span>
          )}
          <span className="text-amber-400">Read-only admin view</span>
        </div>
      </header>

      <div className="space-y-4">
        {data.messages.length === 0 ? (
          <div className="border border-[#2a2a2c] rounded px-4 py-6 text-center text-xs text-gray-500">
            This session has no user or assistant messages.
          </div>
        ) : (
          data.messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: AdminSessionMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={"flex " + (isUser ? "justify-end" : "justify-start")}>
      <div
        className={
          "max-w-[85%] rounded-lg px-4 py-3 text-sm whitespace-pre-wrap break-words " +
          (isUser
            ? "bg-[#1e1e1f] border border-[#2a2a2c]"
            : "bg-transparent")
        }
      >
        <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
          {message.role}
          {message.created_at && (
            <>
              {" · "}
              {new Date(message.created_at).toLocaleString()}
            </>
          )}
          {message.status && message.status !== "complete" && (
            <span className="ml-2 text-amber-400">[{message.status}]</span>
          )}
        </div>
        <div>{message.content}</div>
        {message.tool_calls && message.tool_calls.length > 0 && (
          <details className="mt-2 text-xs text-gray-400">
            <summary className="cursor-pointer">
              Tool calls ({message.tool_calls.length})
            </summary>
            <pre className="mt-2 bg-[#131314] border border-[#2a2a2c] rounded p-2 overflow-x-auto custom-scrollbar text-[11px]">
              {JSON.stringify(message.tool_calls, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </div>
  );
}
