import { useState, useMemo, useRef, useCallback } from "react";
import { Message } from "@/types/chat";

export function usePrompt(messages: Message[]) {
  const [prompt, setPrompt] = useState("");
  const [promptHistory, setPromptHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [tempPrompt, setTempPrompt] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const totalTokens = useMemo(() => {
    const allText = messages.map(m => m.content).join(" ") + " " + prompt;
    return Math.ceil(allText.length / 4);
  }, [messages, prompt]);

  const saveToHistory = useCallback((text: string) => {
    if (!text.trim()) return;
    setPromptHistory(prev => [text, ...prev]);
    setHistoryIndex(-1);
    setTempPrompt("");
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>, onSend: () => void) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    } else if (e.key === "ArrowUp") {
      if (inputRef.current && inputRef.current.selectionStart > 0 && prompt.includes('\n')) return;
      
      if (promptHistory.length > 0) {
        e.preventDefault();
        if (historyIndex === -1) setTempPrompt(prompt);
        const nextIndex = Math.min(historyIndex + 1, promptHistory.length - 1);
        setHistoryIndex(nextIndex);
        setPrompt(promptHistory[nextIndex]);
      }
    } else if (e.key === "ArrowDown") {
      if (inputRef.current && inputRef.current.selectionEnd < prompt.length && prompt.includes('\n')) return;

      if (historyIndex !== -1) {
        e.preventDefault();
        if (historyIndex > 0) {
          const prevIndex = historyIndex - 1;
          setHistoryIndex(prevIndex);
          setPrompt(promptHistory[prevIndex]);
        } else if (historyIndex === 0) {
          setHistoryIndex(-1);
          setPrompt(tempPrompt);
        }
      }
    }
  };

  return { prompt, setPrompt, totalTokens, inputRef, handleKeyDown, saveToHistory };
}