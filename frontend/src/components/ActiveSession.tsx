"use client";

import React, { useRef, useEffect } from "react";
import { Message, FileUpload } from "@/types/chat"; 
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useSearch } from "@/hooks/useSearch";
import MarkdownRenderer from "./MarkdownRenderer";
import ChatInput from "./ChatInput";
import ChatHeader from "./ChatHeader";
import QuickActions from "./QuickActions";
import ProcessingAnimation from "./ProcessingAnimation";
import SearchBar from "./SearchBar";
import ChatTimestamp from "./ChatTimestamp";

interface ActiveSessionProps {
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
  stopAutoTest: () => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  runTestSuite: (type: "it_demo" | "memory_test" | "tool_chain") => void;
  processUploadQueue: (files: FileUpload[]) => void;
  totalTokens: number;
  isSidebarOpen: boolean;
  setIsSidebarOpen: (val: boolean) => void;
  isLoadingHistory?: boolean;
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

export default function ActiveSession({ 
  workspace, sessionTitle, messages, prompt, setPrompt, uploads, setUploads, isProcessing, isAutoTesting,
  handleInference, stopAutoTest, handleKeyDown, runTestSuite, processUploadQueue, totalTokens,
  isSidebarOpen, setIsSidebarOpen, isLoadingHistory 
}: ActiveSessionProps) {
  
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  
  const { scrollRef, onScroll } = useAutoScroll(messages);
  
  const search = useSearch();

  useEffect(() => {
    if (!search.searchQuery) {
      search.setTotalMatches(0);
      return;
    }

    const timer = setTimeout(() => {
      const marks = document.querySelectorAll('.search-match');
      search.setTotalMatches(marks.length);

      let activeIdx = search.searchIndex;
      if (marks.length > 0 && activeIdx >= marks.length) {
         activeIdx = marks.length - 1;
         search.setSearchIndex(activeIdx);
      }

      marks.forEach((mark, i) => {
        const element = mark as HTMLElement;
        if (i === activeIdx) {
          element.style.backgroundColor = '#3b82f6'; // bg-blue-500
          element.style.color = '#ffffff';           // text-white
          element.classList.add('shadow-sm', 'shadow-blue-900/50', 'z-10');
        } else {
          element.style.backgroundColor = 'rgba(59, 130, 246, 0.2)';
          element.style.color = '#93c5fd';
          element.classList.remove('shadow-sm', 'shadow-blue-900/50', 'z-10');
        }
      });
    });

    return () => clearTimeout(timer);
  }, [messages, search.searchQuery, search.searchIndex, search]); // Re-run when DOM changes

  return (
    <div className="flex flex-col flex-1 min-w-0 h-full bg-[#131314]">
      
      <ChatHeader 
        workspace={workspace} 
        sessionTitle={sessionTitle} 
        isSidebarOpen={isSidebarOpen} 
        setIsSidebarOpen={setIsSidebarOpen} 
        rightActions={<SearchBar {...search} />} 
      />

      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-6 flex flex-col items-center custom-scrollbar">
        <div className="w-full max-w-3xl space-y-6 flex flex-col min-h-full">
            
            {messages.length === 0 && !isLoadingHistory && (
              <QuickActions setPrompt={setPrompt} inputRef={textareaRef} />
            )}

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

              const renderUserMessage = (rawContent: string) => {
                const attachmentRegex = /\[Attached_File:(.*?)\]/g;
                const attachments: string[] = [];
                let match;
                
                while ((match = attachmentRegex.exec(rawContent)) !== null) attachments.push(match[1]);
                const cleanContent = rawContent.replace(attachmentRegex, '').trim();
                
                const escapedQuery = search.searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const parts = cleanContent.split(new RegExp(`(${escapedQuery})`, 'gi'));
                
                const highlighted = parts.map((part, idx) => {
                  if (search.searchQuery && part.toLowerCase() === search.searchQuery.toLowerCase()) {
                    return <mark key={idx} className="search-match rounded-[3px] px-0.5 text-inherit transition-colors duration-200">{part}</mark>
                  }
                  return part;
                });

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
                    <div className="whitespace-pre-wrap">{highlighted}</div>
                  </div>
                );
              };

              return (
                <React.Fragment key={i}>
                  {showTimestamp && (
                    <div className="flex justify-center my-6">
                      <span className="text-xs font-medium text-gray-500 bg-[#1e1f20] border border-[#333537] px-3 py-1 rounded-full">{formatTimestamp(m.timestamp)}</span>
                    </div>
                  )}
                  <div id={`msg-${i}`} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`text-[15px] leading-relaxed ${m.role === 'user' ? 'bg-[#1e1f20] text-[#e3e3e3] rounded-3xl py-2.5 px-5 max-w-[80%] whitespace-pre-wrap' : 'text-[#e3e3e3] w-full max-w-full overflow-hidden'}`}>
                          {m.role === "user" ? (
                            renderUserMessage(m.content)
                          ) : (
                            <MarkdownRenderer 
                              content={m.content} 
                              searchQuery={search.searchQuery} 
                            />
                          )}
                      </div>
                  </div>
                </React.Fragment>
              );
            })}
            {isProcessing && messages.length > 0 && messages[messages.length - 1].role === "assistant" && !messages[messages.length - 1].content && (
              <ProcessingAnimation />
            )}
            <div className="h-6 shrink-0" />
            <div ref={terminalEndRef} />
         </div>
      </div>

      <div className="shrink-0 pb-6 px-4 flex flex-col items-center">
        <ChatInput 
          prompt={prompt} setPrompt={setPrompt}
          uploads={uploads} setUploads={setUploads}
          isProcessing={isProcessing} isAutoTesting={isAutoTesting}
          handleInference={handleInference} stopAutoTest={stopAutoTest}
          handleKeyDown={handleKeyDown} runTestSuite={runTestSuite}
          processUploadQueue={processUploadQueue} totalTokens={totalTokens}
          inputRef={textareaRef}
        />
      </div>
    </div>
  );
}