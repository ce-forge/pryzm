"use client";

import React, { useRef, useEffect, useState, useCallback } from "react";
import { useChatContext } from "@/context/ChatContext"; 
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useSearch } from "@/hooks/useSearch";
import { usePrompt } from "@/hooks/usePrompt";
import ChatInput from "./ChatInput";
import ChatHeader from "./ChatHeader";
import QuickActions from "./QuickActions";
import ProcessingAnimation from "./ProcessingAnimation";
import SearchBar from "./SearchBar";
import ChatTimestamp from "./ChatTimestamp";
import ChatBubble from "./ChatBubble";
import ConfirmModal from "./ConfirmModal";

export default function ActiveSession({ isSidebarOpen, setIsSidebarOpen }: any) {
  const { session, uploader, ai, tester, msgActions, currentIsProcessing, currentIsTesting, handleInference, stopAllInference } = useChatContext();

  const messages = session.messages;
  const activeSessionKey = session.currentSession || "temp_new_chat";
  const myStreamingText = ai.streamingContent[activeSessionKey];

  const promptState = usePrompt(messages);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const { scrollRef, onScroll } = useAutoScroll({
    messages,
    streamingText: myStreamingText ?? "",
    isProcessing: currentIsProcessing,
  });
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string, index: number } | null>(null);

  useEffect(() => {
    const isDesktopPointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

    if (textareaRef.current && activeSessionKey === "temp_new_chat" && isDesktopPointer) {
      textareaRef.current.focus();
    }
  }, [activeSessionKey]);

  const search = useSearch(messages, chatContainerRef);

  const onSubmit = useCallback((e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const text = promptState.prompt.trim();
    if (!text || currentIsProcessing) return; 

    handleInference(text);
    promptState.saveToHistory(text);
    promptState.setPrompt(""); 
  }, [promptState, currentIsProcessing, handleInference]);

  return (
    <div className="flex flex-col flex-1 h-full w-full max-w-[100vw] overflow-hidden bg-[#131314]">
      <ChatHeader sessionTitle={messages.length === 0 ? "" : session.sessionTitle} isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} rightActions={<SearchBar {...search} />} />
      
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto overflow-x-hidden px-2 sm:px-4 py-2 custom-scrollbar w-full min-w-0">
        <div ref={chatContainerRef} className="w-full max-w-3xl mx-auto flex flex-col min-h-full min-w-0">
            
            {session.isInitialLoading && (
              <div className="flex-1 flex items-center justify-center min-h-[40vh]">
                <div className="text-gray-500 text-sm flex items-center gap-2">
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Loading messages…
                </div>
              </div>
            )}

            {!session.isInitialLoading && messages.length === 0 && !currentIsProcessing && (
              <QuickActions setPrompt={promptState.setPrompt} inputRef={textareaRef} />
            )}

            {messages.map((m: any, i: number) => {
              const isLastStreaming = currentIsProcessing && i === messages.length - 1 && m.role === "assistant";

              // Stream text directly into the bubble properties
              const displayContent = (isLastStreaming && myStreamingText) ? myStreamingText : m.content;
              // Prefer the message id so React state survives deletes/inserts; index
              // is a last-resort fallback for the (rare) case a message has no id.
              const stableKey = m.id ?? `idx-${i}`;

              return (
                <React.Fragment key={stableKey}>
                  <ChatTimestamp timestamp={m.timestamp} previousTimestamp={i > 0 ? messages[i-1].timestamp : undefined} isFirstMessage={i === 0} />
                  <ChatBubble
                    message={{ ...m, content: displayContent }}
                    index={i}
                    activeSessionKey={activeSessionKey}
                    searchQuery={search.searchQuery}
                    isStreaming={isLastStreaming}
                    onDeleteRequest={(id, idx) => setDeleteConfirm({ id, index: idx })}
                  />
                </React.Fragment>
              );
            })}
            
            {currentIsProcessing && messages.length > 0 && !myStreamingText && <ProcessingAnimation />}
         </div>
      </div>

      <div className="shrink-0 pb-6 px-4 w-full flex justify-center bg-gradient-to-t from-[#131314] to-transparent">
        <ChatInput 
            prompt={promptState.prompt} setPrompt={promptState.setPrompt} uploads={uploader.uploads} setUploads={uploader.setUploads}
            isProcessing={currentIsProcessing} isAutoTesting={currentIsTesting} handleInference={onSubmit} stopAutoTest={stopAllInference}
            handleKeyDown={(e: any) => promptState.handleKeyDown(e, onSubmit)} 
            runTestSuite={(type: any) => tester.runTestSuite(type, session.currentSession)}
            processUploadQueue={(files: any[]) => uploader.processUploadQueue(files)} 
            totalTokens={promptState.totalTokens} inputRef={textareaRef}
        />
      </div>

      <ConfirmModal 
        isOpen={!!deleteConfirm}
        title="Delete Message?"
        description="This permanently removes the bubble from your history."
        onConfirm={() => { 
            if(deleteConfirm) {
                msgActions.deleteMessage(deleteConfirm.id, deleteConfirm.index); 
                setDeleteConfirm(null); 
            }
        }}
        onCancel={() => setDeleteConfirm(null)}
      />
    </div>
  );
}