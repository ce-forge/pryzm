"use client";

import React, { useRef } from "react";
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
import UserMessage from "./UserMessage";

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

export default function ActiveSession(props: ActiveSessionProps) {
  const { 
    messages, isProcessing, isAutoTesting, prompt, setPrompt, 
    uploads, setUploads, handleInference, stopAutoTest, 
    handleKeyDown, runTestSuite, processUploadQueue, totalTokens,
    workspace, sessionTitle, isSidebarOpen, setIsSidebarOpen, isLoadingHistory
  } = props;

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  const { scrollRef, onScroll } = useAutoScroll(messages);
  
  const search = useSearch(messages);

  return (
    <div className="flex flex-col flex-1 min-w-0 h-full bg-[#131314]">
      <ChatHeader {...props} rightActions={<SearchBar {...search} />} />
      
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-6 flex flex-col items-center custom-scrollbar">
        <div className="w-full max-w-3xl space-y-6 flex flex-col min-h-full">
            {messages.length === 0 && !isLoadingHistory && (
              <QuickActions setPrompt={setPrompt} inputRef={textareaRef} />
            )}

            {messages.map((m, i) => (
              <React.Fragment key={i}>
                <ChatTimestamp 
                  timestamp={m.timestamp} 
                  previousTimestamp={i > 0 ? messages[i-1].timestamp : undefined}
                  isFirstMessage={i === 0}
                />
                
                <div id={`msg-${i}`} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`text-[15px] leading-relaxed ${m.role === 'user' ? 'bg-[#1e1f20] text-[#e3e3e3] rounded-3xl py-2.5 px-5 max-w-[80%] whitespace-pre-wrap' : 'text-[#e3e3e3] w-full max-w-full overflow-hidden'}`}>
                        {m.role === "user" ? (
                          <UserMessage 
                            content={m.content} 
                            searchQuery={search.searchQuery} 
                          />
                        ) : (
                          <MarkdownRenderer 
                            content={m.content} 
                            searchQuery={search.searchQuery} 
                          />
                        )}
                    </div>
                </div>
              </React.Fragment>
            ))}
            
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