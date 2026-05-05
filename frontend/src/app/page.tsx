"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import testSuitePrompts from "../data/test_suite.json";

interface FileUpload {
  id: string;
  file: File;
  status: "pending" | "uploading" | "success" | "error";
  progress: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
}

const formatTime = (isoString?: string) => {
  const date = isoString ? new Date(isoString) : new Date();
  const now = new Date();
  const isToday = date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear();

  const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (isToday) return `Today ${timeStr}`;
  if (isYesterday) return `Yesterday ${timeStr}`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

export default function Home() {
  const router = useRouter();
  const searchParams = useSearchParams();
  
  const urlSessionId = searchParams.get("session");
  const workspace = searchParams.get("workspace") || "it_copilot";
  const isIT = workspace === "it_copilot";

  const [promptHistory, setPromptHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);

  const [currentSession, setCurrentSession] = useState<string | null>(urlSessionId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [isAutoTesting, setIsAutoTesting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [uploads, setUploads] = useState<FileUpload[]>([]);
  
  const isProcessingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const abortTestRef = useRef(false);
  const dragCounter = useRef(0);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    isProcessingRef.current = isProcessing;
  }, [isProcessing]);

  useEffect(() => {
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
  }, [urlSessionId]);

  useEffect(() => {
    async function loadHistory() {
      if (isProcessingRef.current || !currentSession) {
        if (!currentSession) setMessages([]);
        return;
      }
      try {
        const res = await fetch(`http://127.0.0.1:8000/sessions/${currentSession}`);
        if (res.ok) {
          const history = await res.json();
          setMessages(history);
        }
      } catch (error) {
        console.error("Failed to load history:", error);
      }
    }
    loadHistory();
  }, [currentSession]);

  useEffect(() => {
    return () => {
      abortTestRef.current = true;
      if (abortControllerRef.current) abortControllerRef.current.abort();
    };
  }, []);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isProcessing, uploads]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [prompt]);

  const totalTokens = useMemo(() => {
    const allText = messages.map(m => m.content).join(" ") + " " + prompt;
    return Math.ceil(allText.length / 4);
  }, [messages, prompt]);

  const maxTokens = 8192;
  const tokenPercentage = (totalTokens / maxTokens) * 100;
  const tokenColor = tokenPercentage > 90 ? "text-red-400 font-bold" : tokenPercentage > 75 ? "text-amber-400" : "text-slate-500";

  const showTimestampArray = useMemo(() => {
    const result: boolean[] = [];
    let lastShownTime = 0;
    for (const msg of messages) {
      if (msg.role !== "user" || !msg.timestamp) {
        result.push(false);
      } else {
        const msgTime = new Date(msg.timestamp).getTime();
        if (lastShownTime === 0 || (msgTime - lastShownTime) > 30 * 60 * 1000) {
          result.push(true);
          lastShownTime = msgTime;
        } else {
          result.push(false);
        }
      }
    }
    return result;
  }, [messages]);

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) setIsDragging(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setIsDragging(false);
  };
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); e.stopPropagation(); };

  const extractFilesFromItems = async (items: DataTransferItemList): Promise<File[]> => {
    const validFiles: File[] = [];
    const queue: any[] = [];
    
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === "file") {
        const entry = item.webkitGetAsEntry();
        if (entry) queue.push(entry);
      }
    }
    
    while (queue.length > 0) {
      const entry = queue.shift();
      if (!entry) continue;
      
      if (entry.isFile) {
        const file = await new Promise<File>((resolve) => (entry as any).file(resolve));
        if (file.name.endsWith(".txt") || file.name.endsWith(".md")) validFiles.push(file);
      } else if (entry.isDirectory) {
        const dirReader = (entry as any).createReader();
        const entries = await new Promise<any[]>((resolve) => dirReader.readEntries(resolve));
        queue.push(...entries);
      }
    }
    return validFiles;
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setIsDragging(false);
    dragCounter.current = 0;
    
    if (!e.dataTransfer.items) return;
    
    const files = await extractFilesFromItems(e.dataTransfer.items);
    if (files.length === 0) return;
    
    const newUploads = files.map((file) => ({
      id: Math.random().toString(36).substring(7),
      file,
      status: "pending" as const,
      progress: 0,
    }));
    
    setUploads((prev) => [...prev, ...newUploads]);
    processUploadQueue(newUploads);
  };

  const processUploadQueue = async (filesToUpload: FileUpload[]) => {
    for (const uploadItem of filesToUpload) {
      setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "uploading", progress: 50 } : u)));
      
      const formData = new FormData();
      formData.append("file", uploadItem.file);
      formData.append("workspace", workspace);
      
      if (currentSession) {
        formData.append("session_id", currentSession);
      }
      
      try {
        const res = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData });
        if (res.ok) {
          setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "success", progress: 100 } : u)));
        } else {
          setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "error", progress: 0 } : u)));
        }
      } catch (err) {
        setUploads((prev) => prev.map((u) => (u.id === uploadItem.id ? { ...u, status: "error", progress: 0 } : u)));
      }
    }
    setTimeout(() => setUploads((prev) => prev.filter((u) => u.status !== "success")), 3000);
  };

  const sendMessage = async (text: string, activeSessionId: string | null) => {
    setMessages((prev) => [...prev, { role: "user", content: text, timestamp: new Date().toISOString() }]);
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
                  router.replace(`/?workspace=${workspace}&session=${parsed.session_id}`, { scroll: false });                  setCurrentSession(parsed.session_id);
                  window.dispatchEvent(new Event("chatCreated"));
                }
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
            } catch (err) {
              console.error("Error parsing stream JSON:", err);
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === "AbortError") {
        console.log("Stream cleanly aborted by user navigation.");
        return updatedSessionId;
      }
      setMessages((prev) => [...prev, { role: "assistant", content: `\n\n[Connection Failure: ${error.message}]` }]);
    } finally {
      setIsProcessing(false);
      abortControllerRef.current = null;
    }
    return updatedSessionId;
  };

  const handleInference = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!prompt.trim() || isProcessing || isAutoTesting) return;
    
    const textToSend = prompt;
    
    setPromptHistory(prev => [textToSend, ...prev]);
    setHistoryIndex(-1); 
    
    setPrompt("");
    
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus(); 
    }
    
    await sendMessage(textToSend, currentSession);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleInference();
    } 
    else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (promptHistory.length > 0) {
        const nextIndex = historyIndex + 1 < promptHistory.length ? historyIndex + 1 : historyIndex;
        setHistoryIndex(nextIndex);
        setPrompt(promptHistory[nextIndex]);
      }
    } 
    else if (e.key === "ArrowDown") {
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

  return (
    <div 
      className={`relative flex flex-col h-full w-full transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-900' : 'bg-stone-900'}`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <div className="flex flex-col h-full p-6 max-w-4xl mx-auto w-full relative z-10">
        
        <header className={`mb-6 flex justify-between items-end border-b pb-4 transition-colors duration-500 ease-in-out ${isIT ? 'border-slate-800' : 'border-stone-800'}`}>
          <div>
            <h1 className={`text-2xl font-bold tracking-tight transition-colors duration-500 ease-in-out ${isIT ? 'text-blue-400' : 'text-orange-400'}`}>
              {isIT ? 'DaiNamik Pryzm' : 'Personal AI'}
            </h1>
            <p className="text-sm text-slate-400">
              {isIT ? 'IT Service Coordinator' : 'General Purpose Assistant'}
            </p>
          </div>
          
          <button 
            onClick={toggleDebugSuite}
            disabled={isProcessing && !isAutoTesting} 
            className={`px-4 py-2 text-sm font-semibold rounded-lg shadow-lg transition-colors duration-300 cursor-pointer disabled:cursor-not-allowed ${
              isAutoTesting 
                ? 'bg-red-600 hover:bg-red-500 text-white animate-pulse' 
                : (isIT ? 'bg-slate-800 hover:bg-blue-600 text-slate-300 hover:text-white' : 'bg-stone-800 hover:bg-orange-600 text-stone-300 hover:text-white')
            }`}
          >
            {isAutoTesting ? "⏹ STOP TESTS" : "🧪 Run Tests"}
          </button>
        </header>

        <div className={`flex-1 border rounded-lg p-4 font-mono text-sm overflow-y-auto shadow-2xl mb-4 custom-scrollbar transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-950 border-slate-700' : 'bg-stone-950 border-stone-700'}`}>
          {messages.length === 0 ? (
            <div className="text-slate-500">// System online</div>
          ) : (
            <div className="space-y-6">
              {messages.map((msg, idx) => (
                <div key={idx} className={msg.role === "user" ? (isIT ? "text-blue-400" : "text-orange-400") : "text-slate-300"}>
                  
                  <div className="flex items-center mb-1">
                    <span className="opacity-50 select-none font-bold">
                      {msg.role === "user" ? "orbital@forge:~$" : "pryzm-ai@node:~#"}
                    </span>
                    {showTimestampArray[idx] && (
                      <span className="ml-2 text-[10px] opacity-40 select-none bg-black/20 px-2 py-0.5 rounded-full border border-white/5">
                        {formatTime(msg.timestamp)}
                      </span>
                    )}
                  </div>
                  
                  <div className="leading-relaxed">
                    {msg.role === "user" ? (
                      <span className="whitespace-pre-wrap">{msg.content}</span>
                    ) : (
                      <ReactMarkdown
                        components={{
                          code({ className, children, ...rest }) {
                            const match = /language-(\w+)/.exec(className || "");
                            return match ? (
                              <div className="bg-black text-emerald-400 p-3 rounded-md border border-slate-700 my-3 overflow-x-auto font-mono text-xs shadow-inner">
                                <code {...rest} className={className}>{children}</code>
                              </div>
                            ) : (
                              <code {...rest} className="bg-slate-800 text-emerald-300 px-1.5 py-0.5 rounded text-xs">{children}</code>
                            );
                          },
                          strong({ children }) { return <strong className="font-bold text-white">{children}</strong>; },
                          ul({ children }) { return <ul className="list-disc list-inside my-2 ml-4">{children}</ul>; }
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                    )}
                  </div>
                </div>
              ))}
              {isProcessing && (
                <div className="text-slate-500 animate-pulse mt-6">
                  <span className="opacity-50 mr-2">pryzm-ai@node:~#</span>
                  thinking...
                </div>
              )}
              <div ref={terminalEndRef} />
            </div>
          )}
        </div>

        <div className="flex flex-col shrink-0 relative">
          
          {uploads.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {uploads.map((upload) => (
                <div key={upload.id} className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-mono shadow-sm transition-all duration-300 border ${upload.status === "success" ? "bg-emerald-900/40 border-emerald-700 text-emerald-400" : upload.status === "error" ? "bg-red-900/40 border-red-700 text-red-400" : "bg-slate-800 border-slate-700 text-slate-300"}`}>
                  <svg className="w-4 h-4 opacity-70" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
                  <span className="truncate max-w-[150px]">{upload.file.name}</span>
                  {upload.status === "uploading" && <svg className="w-3 h-3 animate-spin text-blue-400" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>}
                  {upload.status === "success" && <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>}
                  {upload.status === "error" && <svg className="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" /></svg>}
                </div>
              ))}
            </div>
          )}

          <div className="relative">
            {isDragging && (
              <div className={`absolute -inset-1 z-50 flex items-center justify-center rounded-xl backdrop-blur-md transition-all border-2 border-dashed pointer-events-none animate-pulse ${isIT ? 'border-blue-500 bg-slate-900/90' : 'border-orange-500 bg-stone-900/90'}`}>
                <h2 className={`text-lg font-bold tracking-tight flex items-center gap-3 ${isIT ? 'text-blue-400' : 'text-orange-400'}`}>
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>
                  Drop Files or Folders
                </h2>
              </div>
            )}

            <form onSubmit={handleInference} className="flex gap-4 items-end">
              <textarea
                ref={textareaRef}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isAutoTesting} 
                placeholder="Ask anything here..."
                rows={2}
                className={`flex-1 px-4 py-3 rounded-lg border focus:outline-none text-slate-100 font-mono text-sm resize-none overflow-y-auto custom-scrollbar transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-800 border-slate-600 focus:border-blue-500' : 'bg-stone-800 border-stone-600 focus:border-orange-500'}`}
                style={{ minHeight: '72px', maxHeight: '200px' }}
              />
              
              <div className="flex flex-col items-center gap-1.5 pb-1 shrink-0 w-[110px]">
                <span className={`text-[10px] uppercase tracking-wider font-bold transition-colors ${tokenColor}`}>
                  ~{totalTokens.toLocaleString()} / {maxTokens}
                </span>
                <button
                  type="submit"
                  disabled={isProcessing || isAutoTesting || !prompt.trim()}
                  className={`w-full py-3 h-[46px] rounded-lg font-semibold shadow-lg transition-colors duration-500 ease-in-out cursor-pointer disabled:cursor-not-allowed ${isProcessing || isAutoTesting || !prompt.trim() ? (isIT ? 'bg-slate-800 text-slate-500' : 'bg-stone-800 text-stone-500') : (isIT ? 'bg-blue-600 hover:bg-blue-500 text-white' : 'bg-orange-600 hover:bg-orange-500 text-white')}`}
                >
                  Execute
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}