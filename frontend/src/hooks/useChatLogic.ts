import { useState, useRef, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export interface FileUpload {
  id: string;
  file: File;
  status: "pending" | "uploading" | "success" | "error";
  progress: number;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
}

import testSuitePrompts from "../data/test_suite.json";

export function useChatLogic() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const urlSessionId = searchParams.get("session");
  const workspace = searchParams.get("workspace") || "it_copilot";

  const [currentSession, setCurrentSession] = useState<string | null>(urlSessionId);
  const [sessionTitle, setSessionTitle] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const[prompt, setPrompt] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const[isAutoTesting, setIsAutoTesting] = useState(false);
  const [uploads, setUploads] = useState<FileUpload[]>([]);
  
  const [promptHistory, setPromptHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  const isProcessingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const abortTestRef = useRef(false);
  
  const isNavigatingRef = useRef(false);

  useEffect(() => {
    isProcessingRef.current = isProcessing;
  }, [isProcessing]);

  useEffect(() => {
    if (isNavigatingRef.current) {
        if (urlSessionId === currentSession) {
            isNavigatingRef.current = false;
        }
        return;
    }

    if (urlSessionId !== currentSession) {
      abortTestRef.current = true;
      setIsAutoTesting(false);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      setIsProcessing(false);
      setCurrentSession(urlSessionId);
    }
  }, [urlSessionId, currentSession]);

  useEffect(() => {
    async function loadHistory() {
      if (isProcessingRef.current || !currentSession) {
        if (!currentSession && !isProcessingRef.current) {
            setMessages([]);
            setSessionTitle(""); 
        }
        return;
      }
      try {
        const res = await fetch(`http://127.0.0.1:8000/sessions/${currentSession}`);
        if (res.ok) {
          const history = await res.json();
          setMessages(history);
        }
        
        const sessionRes = await fetch(`http://127.0.0.1:8000/sessions?workspace=${workspace}`);
        if (sessionRes.ok) {
            const sessionData = await sessionRes.json();
            const activeSesh = sessionData.find((x: any) => x.id === currentSession);
            if (activeSesh) setSessionTitle(activeSesh.title);
        }
      } catch (error) {
        console.error("Failed to load history:", error);
      }
    }
    loadHistory();
  },[currentSession, workspace]);

  useEffect(() => {
    const handleChatCreated = async () => {
        if (!currentSession) return;
        try {
            const sessionRes = await fetch(`http://127.0.0.1:8000/sessions?workspace=${workspace}`);
            if (sessionRes.ok) {
                const sessionData = await sessionRes.json();
                const activeSesh = sessionData.find((x: any) => x.id === currentSession);
                if (activeSesh) setSessionTitle(activeSesh.title);
            }
        } catch(e) {}
    };
    window.addEventListener("chatCreated", handleChatCreated);
    return () => window.removeEventListener("chatCreated", handleChatCreated);
  }, [currentSession, workspace]);

  useEffect(() => {
    return () => {
      abortTestRef.current = true;
      if (abortControllerRef.current) abortControllerRef.current.abort();
    };
  },[]);

  const totalTokens = useMemo(() => {
    const allText = messages.map(m => m.content).join(" ") + " " + prompt;
    return Math.ceil(allText.length / 4);
  }, [messages, prompt]);

  const processUploadQueue = async (filesToUpload: FileUpload[]) => {
    // Keep a localized tracker so multiple rapid uploads all link to the newly created session
    let activeSessionForUploads = currentSession;
    
    for (const uploadItem of filesToUpload) {
      setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "uploading", progress: 50 } : u)));
      
      const formData = new FormData();
      formData.append("file", uploadItem.file);
      formData.append("workspace", workspace);
      if (activeSessionForUploads) formData.append("session_id", activeSessionForUploads);
      
      try {
        const res = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData });
        if (res.ok) {
          const data = await res.json();
          setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "success", progress: 100 } : u)));
          
          // FIX: If the backend created a new Session ID for this file, ADOPT IT!
          if (!activeSessionForUploads && data.session_id) {
             activeSessionForUploads = data.session_id;
             setCurrentSession(data.session_id);
             isNavigatingRef.current = true;
             router.replace(`/?workspace=${workspace}&session=${data.session_id}`, { scroll: false });
             window.dispatchEvent(new Event("chatCreated"));
          }
        } else {
          setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "error", progress: 0 } : u)));
        }
      } catch (err) {
        setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "error", progress: 0 } : u)));
      }
    }
    setTimeout(() => setUploads((prev) => prev.filter((u) => u.status !== "error")), 3000);
  };

  const sendMessage = async (text: string, activeSessionId: string | null) => {
    setMessages((prev) =>[...prev, { role: "user", content: text, timestamp: new Date().toISOString() }]);
    setIsProcessing(true);
    let updatedSessionId = activeSessionId;

    abortControllerRef.current = new AbortController();

    try {
      const res = await fetch("http://127.0.0.1:8000/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, session_id: activeSessionId, mode: workspace }),
        signal: abortControllerRef.current.signal
      });

      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);

      setMessages((prev) => [...prev, { role: "assistant", content: "", timestamp: new Date().toISOString() }]);

      const reader = res.body?.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let fullAssistantMessage = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const parsed = JSON.parse(line);
              
              if (parsed.status === "started" && parsed.session_id) {
                updatedSessionId = parsed.session_id;
                if (!activeSessionId) {
                  isNavigatingRef.current = true; 
                  setCurrentSession(parsed.session_id);
                  router.replace(`/?workspace=${workspace}&session=${parsed.session_id}`, { scroll: false });
                }
                window.dispatchEvent(new Event("chatCreated"));
              }

              if (parsed.chunk !== undefined) {
                fullAssistantMessage += parsed.chunk;
                setMessages((prev) => {
                  const newMsgs = [...prev];
                  const lastIndex = newMsgs.length - 1;
                  if (lastIndex >= 0 && newMsgs[lastIndex].role === "assistant") {
                    newMsgs[lastIndex] = { ...newMsgs[lastIndex], content: fullAssistantMessage };
                  }
                  return newMsgs;
                });
              }
            } catch (err) { }
          }
        }
      }
    } catch (error: any) {
      if (error.name === "AbortError") return updatedSessionId;
      setMessages((prev) =>[...prev, { role: "assistant", content: `\n\n[Connection Failure: ${error.message}]` }]);
    } finally {
      setIsProcessing(false);
      abortControllerRef.current = null;
    }
    return updatedSessionId;
  };

  const handleInference = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!prompt.trim() || isProcessing || isAutoTesting) return;
    
    const successfulUploads = uploads.filter(u => u.status === 'success');
    let attachedPrefix = "";
    
    if (successfulUploads.length > 0) {
      attachedPrefix = successfulUploads.map(u => `[Attached_File:${u.file.name}]`).join('\n') + '\n';
    }
    
    const textToSend = attachedPrefix + prompt;
    
    setPromptHistory(prev => [prompt, ...prev]);
    setHistoryIndex(-1); 
    setPrompt("");
    
    setUploads(prev => prev.filter(u => u.status !== 'success'));
    
    await sendMessage(textToSend, currentSession);
  };

  const toggleDebugSuite = async () => {
    if (isAutoTesting) {
      abortTestRef.current = true;
      setIsAutoTesting(false);
      return;
    }
    if (!confirm("Start automated test suite?")) return;
    
    abortTestRef.current = false;
    setIsAutoTesting(true);
    let sessionForTest = currentSession;
    
    for (const testPrompt of testSuitePrompts) {
      if (abortTestRef.current) break;
      const resultId = await sendMessage(testPrompt, sessionForTest);
      if (resultId) sessionForTest = resultId;
      
      for (let i = 0; i < 30; i++) {
        if (abortTestRef.current) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    }
    setIsAutoTesting(false);
    abortTestRef.current = false;
  };

  const stopInference = () => {
    if (abortControllerRef.current) abortControllerRef.current.abort();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleInference();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (promptHistory.length > 0) {
        const nextIndex = historyIndex + 1 < promptHistory.length ? historyIndex + 1 : historyIndex;
        setHistoryIndex(nextIndex);
        setPrompt(promptHistory[nextIndex]);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyIndex > 0) {
        const prevIndex = historyIndex - 1;
        setHistoryIndex(prevIndex);
        setPrompt(promptHistory[prevIndex]);
      } else if (historyIndex === 0) {
        setHistoryIndex(-1);
        setPrompt("");
      }
    }
  };

  return { workspace, sessionTitle, messages, prompt, setPrompt, uploads, setUploads, isProcessing, isAutoTesting, handleInference, stopInference, handleKeyDown, toggleDebugSuite, processUploadQueue, totalTokens };
}