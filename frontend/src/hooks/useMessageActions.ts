import { useCallback } from "react";

export function useMessageActions(
  workspace: string,
  activeSessionKey: string,
  messages: any[],
  setMessageCache: any,
  sendMessage: any,
  navigateToSession: (id: string) => void,
  selectedModel: string
) {
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const saveEdit = useCallback(async (msgId: string | undefined, index: number, newContent: string, rerun: boolean) => {
    if (!msgId || msgId.startsWith('temp-')) return;

    await fetch(`${API_URL}/messages/${msgId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newContent })
    });

    if (rerun) {
      // Truncate everything AFTER this user message
      await fetch(`${API_URL}/sessions/${activeSessionKey}/truncate/${msgId}`, { method: "DELETE" });
      const truncated = messages.slice(0, index + 1);
      truncated[index] = { ...truncated[index], content: newContent };
      setMessageCache((prev: any) => ({ ...prev, [activeSessionKey]: truncated }));
      
      // Fire generation with skip_db_save = true
      sendMessage(newContent, activeSessionKey, selectedModel, [], true);
    } else {
      const updated = [...messages];
      updated[index] = { ...updated[index], content: newContent };
      setMessageCache((prev: any) => ({ ...prev, [activeSessionKey]: updated }));
    }
  }, [messages, activeSessionKey, setMessageCache, sendMessage, API_URL, selectedModel]);

  const deleteMessage = useCallback(async (msgId: string | undefined, index: number) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    const isPair = messages[index].role === "user" && messages[index+1]?.role === "assistant";
    const newMessages = [...messages];
    const assistantId = isPair ? messages[index+1].id : null;
    newMessages.splice(index, isPair ? 2 : 1);
    setMessageCache((prev: any) => ({ ...prev, [activeSessionKey]: newMessages }));
    await fetch(`${API_URL}/messages/${msgId}`, { method: "DELETE" });
    if (assistantId) await fetch(`${API_URL}/messages/${assistantId}`, { method: "DELETE" });
  }, [messages, activeSessionKey, setMessageCache, API_URL]);

  const branchSession = useCallback(async (msgId: string) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    
    try {
      const res = await fetch(`${API_URL}/sessions/${activeSessionKey}/branch?up_to_message_id=${msgId}`, {
        method: "POST"
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
  }, [activeSessionKey, API_URL, navigateToSession]);

  const rerunAssistant = useCallback(async (index: number) => {
    if (index === 0 || messages[index].role !== 'assistant') return;
    
    // Find the user message immediately preceding this AI response
    const userMsg = messages[index - 1];
    if (!userMsg || userMsg.role !== 'user') return;

    // Truncate the DB starting right after the user message
    await fetch(`${API_URL}/sessions/${activeSessionKey}/truncate/${userMsg.id}`, { method: "DELETE" });

    // Truncate UI Cache to remove the old AI message and anything below it
    const truncated = messages.slice(0, index); 
    setMessageCache((prev: any) => ({ ...prev, [activeSessionKey]: truncated }));

    // Trigger generation based on the existing userMsg content
    sendMessage(userMsg.content, activeSessionKey, selectedModel, [], true);
  }, [messages, activeSessionKey, setMessageCache, sendMessage, API_URL, selectedModel]);

  return { 
    deleteMessage, 
    saveEdit, 
    branchSession, 
    rerunAssistant
  }; 
}