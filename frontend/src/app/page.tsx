"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function Home() {
  const router = useRouter();
  const searchParams = useSearchParams();
  
  const urlSessionId = searchParams.get("session");

  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  
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

const handleInference = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isProcessing) return;

    const currentPrompt = prompt;
    setMessages((prev) => [...prev, { role: "user", content: currentPrompt }]);
    setPrompt("");
    setIsProcessing(true);

    try {
      const res = await fetch("http://127.0.0.1:8000/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          prompt: currentPrompt,
          session_id: urlSessionId 
        }),
      });

      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);

      // Add an empty assistant message to the screen that we will "fill up"
      setMessages((prev) =>[...prev, { role: "assistant", content: "" }]);
      setIsProcessing(false); // We can stop the 'loading' pulse because text is arriving!

      // Connect to the stream
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
              
              if (parsed.done && !urlSessionId) {
                router.push(`/?session=${parsed.session_id}`);
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
  };

  return (
    <div className="flex flex-col h-full p-6 max-w-4xl mx-auto w-full">
      <header className="mb-6 flex justify-between items-end border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-emerald-400">DaiNamik Pryzm</h1>
          <p className="text-sm text-slate-400">IT Service Coordinator</p>
        </div>
      </header>

      <div className="flex-1 bg-slate-950 border border-slate-700 rounded-lg p-4 font-mono text-sm overflow-y-auto shadow-2xl mb-4 custom-scrollbar">
        {messages.length === 0 ? (
          <div className="text-slate-500">// System online</div>
        ) : (
          <div className="space-y-6">
            {messages.map((msg, idx) => (
              <div key={idx} className={msg.role === "user" ? "text-emerald-400" : "text-slate-300"}>
                <span className="opacity-50 mr-2 select-none">
                  {msg.role === "user" ? "orbital@forge:~$" : "pryzm-ai@node:~#"}
                </span>
                <span className="whitespace-pre-wrap leading-relaxed">{msg.content}</span>
              </div>
            ))}
            {isProcessing && (
              <div className="text-slate-500 animate-pulse">
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
          disabled={isProcessing}
          placeholder="Ask anything here..."
          className="flex-1 px-4 py-3 rounded-lg bg-slate-800 border border-slate-600 focus:outline-none focus:border-emerald-500 transition-colors text-slate-100 font-mono text-sm"
        />
        <button
          type="submit"
          disabled={isProcessing || !prompt.trim()}
          className="px-6 py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 font-semibold transition-colors shadow-lg"
        >
          Execute
        </button>
      </form>
    </div>
  );
}