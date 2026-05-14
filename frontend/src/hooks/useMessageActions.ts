import { useCallback } from "react";
import { apiFetch } from "@/utils/apiClient";

export function useMessageActions(
  workspace: string,
  activeSessionKey: string,
  activeCacheKey: string,
  messages: any[],
  setMessageCache: any,
  sendMessage: any,
  navigateToSession: (id: string) => void,
  selectedModel: string
) {
  const saveEdit = useCallback(async (msgId: string | undefined, index: number, newContent: string, rerun: boolean) => {
    if (!msgId || msgId.startsWith('temp-')) return;

    await apiFetch(`/messages/${msgId}?workspace=${workspace}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newContent })
    });

    if (rerun) {
      // Truncate everything AFTER this user message
      await apiFetch(`/sessions/${activeSessionKey}/truncate/${msgId}?workspace=${workspace}`, { method: "DELETE" });
      const truncated = messages.slice(0, index + 1);
      truncated[index] = { ...truncated[index], content: newContent };
      setMessageCache((prev: any) => ({ ...prev, [activeCacheKey]: truncated }));

      // Fire generation with skip_db_save = true
      sendMessage(newContent, activeSessionKey, selectedModel, [], true);
    } else {
      const updated = [...messages];
      updated[index] = { ...updated[index], content: newContent };
      setMessageCache((prev: any) => ({ ...prev, [activeCacheKey]: updated }));
    }
  }, [messages, activeSessionKey, activeCacheKey, setMessageCache, sendMessage, workspace, selectedModel]);

  const deleteMessage = useCallback(async (msgId: string | undefined, index: number) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    const isPair = messages[index].role === "user" && messages[index+1]?.role === "assistant";
    const newMessages = [...messages];
    const assistantId = isPair ? messages[index+1].id : null;
    newMessages.splice(index, isPair ? 2 : 1);
    setMessageCache((prev: any) => ({ ...prev, [activeCacheKey]: newMessages }));
    await apiFetch(`/messages/${msgId}?workspace=${workspace}`, { method: "DELETE" });
    if (assistantId) await apiFetch(`/messages/${assistantId}?workspace=${workspace}`, { method: "DELETE" });
  }, [messages, activeCacheKey, setMessageCache, workspace]);

  const branchSession = useCallback(async (msgId: string) => {
    if (!msgId || msgId.startsWith('temp-')) return;

    try {
      const res = await apiFetch(`/sessions/${activeSessionKey}/branch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ up_to_message_id: msgId }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.new_session_id) {
          navigateToSession(data.new_session_id);
        }
      }
    } catch (err) {
      console.error("Failed to branch session:", err);
    }
  }, [activeSessionKey, navigateToSession]);

  const rerunAssistant = useCallback(async (index: number) => {
    if (index === 0 || messages[index].role !== 'assistant') return;

    // Find the user message immediately preceding this AI response
    const userMsg = messages[index - 1];
    if (!userMsg || userMsg.role !== 'user') return;

    // Truncate the DB starting right after the user message
    await apiFetch(`/sessions/${activeSessionKey}/truncate/${userMsg.id}?workspace=${workspace}`, { method: "DELETE" });

    // Truncate UI Cache to remove the old AI message and anything below it
    const truncated = messages.slice(0, index);
    setMessageCache((prev: any) => ({ ...prev, [activeCacheKey]: truncated }));

    // Trigger generation based on the existing userMsg content
    sendMessage(userMsg.content, activeSessionKey, selectedModel, [], true);
  }, [messages, activeSessionKey, activeCacheKey, setMessageCache, sendMessage, workspace, selectedModel]);

  return {
    deleteMessage, 
    saveEdit, 
    branchSession, 
    rerunAssistant
  }; 
}