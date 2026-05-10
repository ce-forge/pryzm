"use client";

import React, { useRef, useEffect } from "react";
import { useChatContext } from "@/context/ChatContext"; 
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useSearch } from "@/hooks/useSearch";
import { usePrompt } from "@/hooks/usePrompt";
import MarkdownRenderer from "./MarkdownRenderer";
import ChatInput from "./ChatInput";
import ChatHeader from "./ChatHeader";
import QuickActions from "./QuickActions";
import ProcessingAnimation from "./ProcessingAnimation";
import SearchBar from "./SearchBar";
import ChatTimestamp from "./ChatTimestamp";
import UserMessage from "./UserMessage";

interface ActiveSessionProps {
  isSidebarOpen: boolean;
  setIsSidebarOpen: (val: boolean) => void;
}

export default function ActiveSession({ isSidebarOpen, setIsSidebarOpen }: ActiveSessionProps) {
  const { 
    session, uploader, ai, tester, 
    currentIsProcessing, currentIsTesting, 
    handleInference, stopAllInference 
  } = useChatContext();

  const messages = session.isInitialLoading ? [] : session.messages;
  
  const activeSessionKey = session.currentSession || "temp_new_chat";
  const myStreamingText = ai.streamingContent[activeSessionKey];

  const activeTitle = (!session.currentSession || session.currentSession.startsWith("optimistic-")) 
    ? "" 
    : session.sessionTitle;

  const promptState = usePrompt(messages);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  
  const { scrollRef, onScroll, scrollToBottom } = useAutoScroll(messages);

  useEffect(() => {
    if (currentIsProcessing && myStreamingText) {
      scrollToBottom();
    }
  }, [myStreamingText, currentIsProcessing, scrollToBottom]);

  const search = useSearch(messages, chatContainerRef);

  const onLocalSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!promptState.prompt.trim() || currentIsProcessing) return;
    
    handleInference(promptState.prompt);
    promptState.saveToHistory(promptState.prompt);
    promptState.setPrompt(""); 
  };

  return (
    <div className="flex flex-col flex-1 min-w-0 h-full bg-[#131314]">
      <ChatHeader 
         workspace={session.workspace} 
         sessionTitle={activeTitle} 
         isSidebarOpen={isSidebarOpen} 
         setIsSidebarOpen={setIsSidebarOpen} 
         rightActions={<SearchBar {...search} />} 
      />
      
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-6 flex flex-col items-center custom-scrollbar">
        <div ref={chatContainerRef} className="w-full max-w-3xl space-y-6 flex flex-col min-h-full">
            {messages.length === 0 && !session.isInitialLoading && (
              <QuickActions setPrompt={promptState.setPrompt} inputRef={textareaRef} />
            )}

            {messages.map((m: any, i: number) => {
              const isLastAndStreaming = currentIsProcessing && i === messages.length - 1 && m.role === "assistant";
              const displayContent = isLastAndStreaming ? (myStreamingText || m.content) : m.content;

              return (
                <React.Fragment key={i}>
                  <ChatTimestamp timestamp={m.timestamp} previousTimestamp={i > 0 ? messages[i-1].timestamp : undefined} isFirstMessage={i === 0} />
                  <div id={`msg-${i}`} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`text-[15px] leading-relaxed ${m.role === 'user' ? 'bg-[#1e1f20] text-[#e3e3e3] rounded-3xl py-2.5 px-5 max-w-[80%] whitespace-pre-wrap' : 'text-[#e3e3e3] w-full max-w-full overflow-hidden'}`}>
                          {m.role === "user" ? (
                            <UserMessage content={displayContent} searchQuery={search.searchQuery} />
                          ) : (
                            <MarkdownRenderer content={displayContent} searchQuery={search.searchQuery} />
                          )}
                      </div>
                  </div>
                </React.Fragment>
              );
            })}
            
            {currentIsProcessing && messages.length > 0 && messages[messages.length - 1].role === "assistant" && !myStreamingText && !messages[messages.length - 1].content && (
              <ProcessingAnimation />
            )}
            <div className="h-6 shrink-0" />
         </div>
      </div>

      <div className="shrink-0 pb-6 px-4 flex flex-col items-center">
        <ChatInput 
          prompt={promptState.prompt} 
          setPrompt={promptState.setPrompt}
          uploads={uploader.uploads} 
          setUploads={uploader.setUploads}
          isProcessing={currentIsProcessing} 
          isAutoTesting={currentIsTesting}
          handleInference={onLocalSubmit} 
          stopAutoTest={stopAllInference}
          handleKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => promptState.handleKeyDown(e, onLocalSubmit)} 
          runTestSuite={(type: "it_demo" | "memory_test" | "tool_chain") => tester.runTestSuite(type, session.currentSession)}
          processUploadQueue={(files: any[]) => uploader.processUploadQueue(files, session.currentSession)} 
          totalTokens={promptState.totalTokens} 
          inputRef={textareaRef}
        />
      </div>
    </div>
  );
}