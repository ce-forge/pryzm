"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import testSuitePrompts from "../data/test_suite.json";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function Home() {
  const router = useRouter();
  const searchParams = useSearchParams();
  
  const urlSessionId = searchParams.get("session");
  const workspace = searchParams.get("workspace") || "it_copilot";
  const isIT = workspace === "it_copilot";

  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const[isAutoTesting, setIsAutoTesting] = useState(false);
  
  const abortTestRef = useRef(false);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isProcessing]);

  useEffect(() => {
    async function loadHistory() {
      if (!urlSessionId) {
        setMessages([]);
        return;
      }
      try {
        const res = await fetch(`http://127.0.0.1:8000/sessions/${urlSessionId}`);
        if (res.ok) {
          const history = await res.json();
          setMessages(history);
        }
      } catch (error) {
        console.error("Failed to load history:", error);
      }
    }
    loadHistory();
  }, [urlSessionId]);

  const sendMessage = async (text: string, activeSessionId: string | null) => {
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setIsProcessing(true);
    let updatedSessionId = activeSessionId;

    try {
      const res = await fetch("http://127.0.0.1:8000/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, session_id: activeSessionId, mode: workspace }),
      });

      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);

      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
      setIsProcessing(false); 

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
              if (parsed.chunk) {
                fullAssistantMessage += parsed.chunk;
                setMessages((prev) => {
                  const newMsgs = [...prev];
                  newMsgs[newMsgs.length - 1] = { role: "assistant", content: fullAssistantMessage };
                  return newMsgs;
                });
              }
              if (parsed.done) {
                updatedSessionId = parsed.session_id;
                if (!activeSessionId) {
                  router.push(`/?workspace=${workspace}&session=${parsed.session_id}`);
                }
              }
            } catch (err) {
              console.error("Error parsing stream:", err);
            }
          }
        }
      }
    } catch (error) {
      setMessages((prev) =>[...prev, { role: "assistant", content: `Connection Failure: ${error}` }]);
      setIsProcessing(false);
    }
    return updatedSessionId;
  };

  const handleInference = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isProcessing || isAutoTesting) return;
    const textToSend = prompt;
    setPrompt("");
    await sendMessage(textToSend, urlSessionId);
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
    let currentSession = urlSessionId;
    
    for (const testPrompt of testSuitePrompts) {
      if (abortTestRef.current) break;
      
      currentSession = await sendMessage(testPrompt, currentSession) || null;
      
      for (let i = 0; i < 30; i++) {
        if (abortTestRef.current) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    }
    
    setIsAutoTesting(false);
    abortTestRef.current = false;
  };

  return (
    <div className={`flex flex-col h-full w-full transition-colors duration-500 ease-in-out ${isIT ? 'bg-slate-900' : 'bg-stone-900'}`}>
      <div className="flex flex-col h-full p-6 max-w-4xl mx-auto w-full">
        
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
                  <span className="opacity-50 mr-2 select-none">
                    {msg.role === "user" ? "orbital@forge:~$" : "pryzm-ai@node:~#"}
                  </span>
                  
                  <div className="mt-1 leading-relaxed">
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
                  _awaiting inference...
                </div>
              )}
              <div ref={terminalEndRef} />
            </div>
          )}
        </div>

        <form onSubmit={handleInference} className="flex gap-4 shrink-0">
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isProcessing || isAutoTesting}
            placeholder="Ask anything here..."
            className={`flex-1 px-4 py-3 rounded-lg border focus:outline-none text-slate-100 font-mono text-sm transition-colors duration-500 ease-in-out ${
              isIT ? 'bg-slate-800 border-slate-600 focus:border-blue-500' : 'bg-stone-800 border-stone-600 focus:border-orange-500'
            }`}
          />
          <button
            type="submit"
            disabled={isProcessing || isAutoTesting || !prompt.trim()}
            className={`px-6 py-3 rounded-lg font-semibold shadow-lg transition-colors duration-500 ease-in-out ${
              isProcessing || isAutoTesting || !prompt.trim()
                ? (isIT ? 'bg-slate-800 text-slate-500' : 'bg-stone-800 text-stone-500') 
                : (isIT ? 'bg-blue-600 hover:bg-blue-500 text-white' : 'bg-orange-600 hover:bg-orange-500 text-white') 
            }`}
          >
            Execute
          </button>
        </form>
      </div>
    </div>
  );
}