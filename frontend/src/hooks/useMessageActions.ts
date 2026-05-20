import { useCallback } from "react";
import { apiFetch } from "@/utils/apiClient";
import { withRollback } from "@/utils/withRollback";
import { Message } from "@/types/chat";

export function useMessageActions(
  workspace: string,
  activeSessionKey: string,
  messages: Message[],
  replaceMessages: (workspaceSlug: string, sessionId: string, messages: Message[]) => void,
  sendMessage: (text: string, sessionId: string | null, attachments?: string[], skipUserAdd?: boolean, modes?: string[]) => Promise<string>,
  navigateToSession: (id: string) => void,
  notifySessionCreated: (oldId: string, newId: string) => void,
  currentModes: string[] = [],
) {
  const saveEdit = useCallback(async (msgId: string | undefined, index: number, newContent: string, rerun: boolean) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    const previousMessages = [...messages];

    try {
      await withRollback(
        () => {
          if (rerun) {
            const truncated = messages.slice(0, index + 1);
            truncated[index] = { ...truncated[index], content: newContent };
            replaceMessages(workspace, activeSessionKey, truncated);
          } else {
            const updated = [...messages];
            updated[index] = { ...updated[index], content: newContent };
            replaceMessages(workspace, activeSessionKey, updated);
          }
        },
        () => replaceMessages(workspace, activeSessionKey, previousMessages),
        async () => {
          const r = await apiFetch(`/messages/${msgId}?workspace=${workspace}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: newContent }),
          });
          if (!r.ok) throw new Error("edit failed");
          if (rerun) {
            const tr = await apiFetch(
              `/sessions/${activeSessionKey}/truncate/${msgId}?workspace=${workspace}`,
              { method: "DELETE" },
            );
            if (!tr.ok) throw new Error("truncate failed");
          }
        },
      );

      if (rerun) sendMessage(newContent, activeSessionKey, [], true, currentModes);
    } catch (err) {
      console.error("Message edit failed", err);
    }
  }, [messages, activeSessionKey, replaceMessages, sendMessage, workspace, currentModes]);

  const deleteMessage = useCallback(async (msgId: string | undefined, index: number) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    // Truncate at this point: drop the target message AND every message that
    // came after it. Deleting only the target leaves orphaned downstream turns
    // whose context referenced the now-missing message — almost never what the
    // user wants when they hit the trash icon mid-conversation.
    const newMessages = messages.slice(0, index);
    replaceMessages(workspace, activeSessionKey, newMessages);
    await apiFetch(`/sessions/${activeSessionKey}/truncate/${msgId}?workspace=${workspace}`, { method: "DELETE" });
    await apiFetch(`/messages/${msgId}?workspace=${workspace}`, { method: "DELETE" });
  }, [messages, activeSessionKey, replaceMessages, workspace]);

  const branchSession = useCallback(async (msgId: string) => {
    if (!msgId || msgId.startsWith('temp-')) return;

    try {
      const res = await apiFetch(`/sessions/${activeSessionKey}/branch?workspace=${workspace}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ up_to_message_id: msgId }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.new_session_id) {
          navigateToSession(data.new_session_id);
          notifySessionCreated(activeSessionKey, data.new_session_id);
        }
      }
    } catch (err) {
      console.error("Failed to branch session:", err);
    }
  }, [activeSessionKey, navigateToSession, notifySessionCreated, workspace]);

  const thumbsDown = useCallback(async (index: number) => {
    const msg = messages[index];
    if (!msg || msg.role !== 'assistant') return;
    const params = new URLSearchParams();
    if (activeSessionKey) params.set("session_id", activeSessionKey);
    const path = `/api/bug-reports${params.toString() ? "?" + params.toString() : ""}`;
    const r = await apiFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category: "feedback_negative",
        message: (msg.content || "").slice(0, 1000),
        include_session: true,
      }),
    });
    if (!r.ok) throw new Error("thumbs-down submit failed");
  }, [messages, activeSessionKey]);

  return { deleteMessage, saveEdit, branchSession, thumbsDown };
}
