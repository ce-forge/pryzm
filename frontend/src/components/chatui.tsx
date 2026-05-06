"use client";

import React, { useRef, useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { FileUpload, Message } from "@/hooks/useChatLogic";

interface ChatUIProps {
  workspace: string;
  sessionTitle: string;
  messages: Message[];
  prompt: string;
  setPrompt: (p: string) => void;
  uploads: FileUpload[];
  setUploads: React.Dispatch<React.SetStateAction<FileUpload[]>>;
  isProcessing: boolean;
  isAutoTesting: boolean;
  handleInference: (e?: React.FormEvent) => void;
  stopInference: () => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  toggleDebugSuite: () => void;
  processUploadQueue: (files: FileUpload[]) => void;
  totalTokens: number;
  isSidebarOpen: boolean;
  setIsSidebarOpen: (val: boolean) => void;
}

const formatTimestamp = (timestamp?: string) => {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  
  const time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  
  if (diffDays === 0 && now.getDate() === date.getDate()) return `Today ${time}`;
  if (diffDays === 1 || (diffDays === 0 && now.getDate() !== date.getDate())) return `Yesterday ${time}`;
  return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`;
};

const CodeBlock = ({ language, value }: { language: string, value: string }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative rounded-xl overflow-hidden border border-[#333537] my-4 shadow-lg bg-[#0d0d0d]">
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#1a1b1c] border-b border-[#333537] text-xs text-gray-400 select-none">
        <span className="font-mono lowercase tracking-wide">{language || 'text'}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 hover:text-[#e3e3e3] transition-colors focus:outline-none"
          title="Copy code"
        >
          {copied ? (
            <>
              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
              <span className="text-emerald-400">Copied!</span>
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={vscDarkPlus}
        customStyle={{ margin: 0, padding: '1rem', background: 'transparent', fontSize: '13px' }}
        wrapLines={true}
        wrapLongLines={true}
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
};

export default function ChatUI({ 
  workspace, sessionTitle, messages, prompt, setPrompt, uploads, setUploads, isProcessing, isAutoTesting,
  handleInference, stopInference, handleKeyDown, toggleDebugSuite, processUploadQueue, totalTokens,
  isSidebarOpen, setIsSidebarOpen
}: ChatUIProps) {
  
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isProcessing, uploads]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [prompt]);

  const extractFilesFromItems = async (items: DataTransferItemList): Promise<File[]> => {
    const validFiles: File[] = [];
    const queue: any[] =[];
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
        if (file.name.endsWith(".txt") || file.name.endsWith(".md") || file.name.endsWith(".py") || file.name.endsWith(".csv")) validFiles.push(file);
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
      file, status: "pending" as const, progress: 0,
    }));
    
    setUploads((prev) =>[...prev, ...newUploads]);
    processUploadQueue(newUploads);
  };

  const renderUserMessage = (rawContent: string) => {
    const attachmentRegex = /\[Attached_File:(.*?)\]/g;
    const attachments: string[] =[];
    let match;
    
    while ((match = attachmentRegex.exec(rawContent)) !== null) {
      attachments.push(match[1]);
    }
    
    const cleanContent = rawContent.replace(attachmentRegex, '').trim();
    
    return (
      <div className="flex flex-col items-end">
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2 justify-end">
            {attachments.map((filename, idx) => (
              <div key={idx} className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-[#131314] text-gray-300 border border-[#333537]">
                <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
                {filename}
              </div>
            ))}
          </div>
        )}
        <div className="whitespace-pre-wrap">{cleanContent}</div>
      </div>
    );
  };

  return (
    <div className="flex flex-col flex-1 min-w-0 h-full bg-[#131314]">
      
      <header className="flex items-center justify-between p-4 shrink-0 border-b border-[#333537]/30">
         <div className="flex items-center gap-4">
            {!isSidebarOpen && (
              <button onClick={() => setIsSidebarOpen(true)} className="p-2 hover:bg-[#282a2c] rounded-full text-gray-400">
                 <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
              </button>
            )}
            <div className="flex flex-col">
              <h1 className="text-[16px] text-[#e3e3e3] font-semibold tracking-wide">
                {sessionTitle || 'New Diagnostic Chat'}
              </h1>
              <span className="text-[11px] text-gray-500 font-medium tracking-wider uppercase">
                DaiNamik Pryzm • {workspace === 'it_copilot' ? 'IT Copilot' : 'Personal Workspace'}
              </span>
            </div>
         </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-6 flex flex-col items-center custom-scrollbar">
         <div className="w-full max-w-3xl space-y-6">
            {messages.map((m, i) => {
              let showTimestamp = false;
              if (m.timestamp) {
                if (i === 0) showTimestamp = true;
                else {
                  const prevMsg = messages[i - 1];
                  if (prevMsg.timestamp) {
                    const diff = new Date(m.timestamp).getTime() - new Date(prevMsg.timestamp).getTime();
                    if (diff > 30 * 60 * 1000) showTimestamp = true; 
                  }
                }
              }

              return (
                <React.Fragment key={i}>
                  {showTimestamp && (
                    <div className="flex justify-center my-6">
                      <span className="text-xs font-medium text-gray-500 bg-[#1e1f20] border border-[#333537] px-3 py-1 rounded-full">
                        {formatTimestamp(m.timestamp)}
                      </span>
                    </div>
                  )}
                  <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`text-[15px] leading-relaxed ${m.role === 'user' ? 'bg-[#1e1f20] text-[#e3e3e3] rounded-3xl py-2.5 px-5 max-w-[80%] whitespace-pre-wrap' : 'text-[#e3e3e3] w-full max-w-full overflow-hidden'}`}>
                          {m.role === "user" ? (
                            renderUserMessage(m.content)
                          ) : (
                            <ReactMarkdown
                              components={{
                                p({ children }) { 
                                  if (!children || (typeof children === 'string' && children.trim() === '')) return null;
                                  return <p className="mb-2 last:mb-0">{children}</p>; 
                                },
                                blockquote({ children }) {
                                  return (
                                    <blockquote className="bg-[#1a1b1c] border border-[#333537] border-l-4 border-l-blue-500 text-gray-300 px-4 py-3 rounded-r-lg shadow-md text-[13px] my-3 flex flex-col justify-center">
                                      {children}
                                    </blockquote>
                                  );
                                },
                                // THE FIX: Safely intercept <pre> block code and convert to our CodeBlock widget
                                pre({ children }: any) { 
                                  if (children && children.props) {
                                    const { className, children: codeContent } = children.props;
                                    const match = /language-(\w+)/.exec(className || "");
                                    const lang = match ? match[1] : "text";
                                    const codeString = String(codeContent).replace(/\n$/, "");
                                    return <CodeBlock language={lang} value={codeString} />;
                                  }
                                  return <pre className="my-1.5">{children}</pre>; 
                                },
                                // ONLY applies to inline code like `this`
                                code({ children, ...rest }: any) {
                                  return (
                                    <code {...rest} className="bg-[#1e1f20] text-emerald-300 px-1.5 py-0.5 rounded text-[13px] border border-[#333537]">
                                      {children}
                                    </code>
                                  );
                                },
                                strong({ children }) { return <strong className="font-semibold text-white">{children}</strong>; },
                                ul({ children }) { return <ul className="list-disc list-outside mb-3 ml-4 space-y-1">{children}</ul>; },
                                ol({ children }) { return <ol className="list-decimal list-outside mb-3 ml-4 space-y-1">{children}</ol>; },
                                li({ children }) { return <li className="leading-snug">{children}</li>; },
                              }}
                            >
                              {m.content}
                            </ReactMarkdown>
                          )}
                      </div>
                  </div>
                </React.Fragment>
              );
            })}
            {isProcessing && <div className="text-gray-500 animate-pulse mt-2 text-sm">Pryzm is thinking...</div>}
            <div ref={terminalEndRef} />
         </div>
      </div>

      <div className="shrink-0 pb-6 px-4 flex flex-col items-center">
        <div className="w-full max-w-3xl relative">
            {uploads.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
                {uploads.map((u, i) => (
                <div key={i} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border ${u.status === "success" ? "bg-emerald-900/20 border-emerald-800 text-emerald-400" : "bg-[#1e1f20] border-[#333537] text-gray-300"}`}>
                    {u.status === "uploading" ? <span className="animate-spin">⏳</span> : <span>📎</span>}
                    <span>{u.file.name}</span>
                    
                    {u.status === "success" && (
                      <button
                        type="button"
                        onClick={() => setUploads(prev => prev.filter(up => up.id !== u.id))}
                        className="ml-1 opacity-70 hover:opacity-100 hover:text-white transition-opacity"
                        title="Remove attachment"
                      >
                        ✕
                      </button>
                    )}
                </div>
                ))}
            </div>
            )}

            <div 
               className="relative bg-[#1e1f20] rounded-3xl transition-all duration-200 focus-within:bg-[#282a2c]"
               onDragEnter={(e) => { e.preventDefault(); dragCounter.current++; setIsDragging(true); }}
               onDragLeave={(e) => { e.preventDefault(); dragCounter.current--; if(dragCounter.current===0) setIsDragging(false); }}
               onDragOver={(e) => e.preventDefault()}
               onDrop={handleDrop}
            >
              {isDragging && (
                 <div className="absolute inset-0 z-50 flex items-center justify-center bg-blue-500/10 backdrop-blur-sm rounded-3xl border-2 border-dashed border-blue-500 pointer-events-none">
                    <span className="text-blue-400 font-bold flex items-center gap-2">
                       <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>
                       Drop to upload
                    </span>
                 </div>
              )}

              <form onSubmit={handleInference} className="flex flex-col p-2">
                  <textarea 
                  ref={textareaRef}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={isAutoTesting}
                  className="w-full bg-transparent px-4 pt-3 pb-2 text-[15px] text-[#e3e3e3] resize-none focus:outline-none custom-scrollbar min-h-[50px] max-h-[200px]"
                  placeholder="Ask Pryzm anything..."
                  />
                  
                  <div className="flex justify-between items-center px-2 pb-1">
                      <div className="flex gap-2 items-center">
                          <button type="button" onClick={toggleDebugSuite} className={`p-2 rounded-full transition-colors ${isAutoTesting ? 'bg-red-500 text-white animate-pulse' : 'text-gray-400 hover:bg-[#333537]'}`} title="Run Test Suite">
                              <span className="text-sm">🧪</span>
                          </button>
                          <span className="text-[10px] text-gray-500 ml-2 font-mono">~{totalTokens} / 8192</span>
                      </div>
                      
                      {isProcessing ? (
                          <button type="button" onClick={stopInference} className="p-2 bg-[#333537] rounded-full text-white flex items-center justify-center">
                              <div className="w-4 h-4 bg-white rounded-sm"></div>
                          </button>
                      ) : (
                          <button type="submit" disabled={!prompt.trim() || isAutoTesting} className="p-2 bg-[#e3e3e3] hover:bg-white disabled:bg-[#333537] disabled:text-gray-500 rounded-full text-black transition-colors">
                              <svg className="w-5 h-5 ml-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                          </button>
                      )}
                  </div>
              </form>
            </div>
        </div>
      </div>
    </div>
  );
}