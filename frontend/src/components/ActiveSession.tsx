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

  const messages = session.isInitialLoading ? [] : session.messages;
  const activeSessionKey = session.currentSession || "temp_new_chat";
  const myStreamingText = ai.streamingContent[activeSessionKey];

  const promptState = usePrompt(messages);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const { scrollRef, onScroll, scrollToBottom } = useAutoScroll(messages);
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string, index: number } | null>(null);

  useEffect(() => {
    if (currentIsProcessing && myStreamingText) {
      scrollToBottom();
    } else if (!currentIsProcessing) {
      const timer = setTimeout(() => scrollToBottom(), 50);
      return () => clearTimeout(timer);
    }
  }, [myStreamingText, currentIsProcessing, scrollToBottom]);

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
      <ChatHeader workspace={session.workspace} sessionTitle={session.sessionTitle} isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} rightActions={<SearchBar {...search} />} />
      
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto overflow-x-hidden px-2 sm:px-4 py-2 custom-scrollbar w-full min-w-0">
        <div ref={chatContainerRef} className="w-full max-w-3xl mx-auto flex flex-col min-h-full min-w-0">
            
            {messages.length === 0 && !session.isInitialLoading && !currentIsProcessing && (
              <QuickActions setPrompt={promptState.setPrompt} inputRef={textareaRef} />
            )}

            {messages.map((m: any, i: number) => {
              const isLastStreaming = currentIsProcessing && i === messages.length - 1 && m.role === "assistant";
              
              // Stream text directly into the bubble properties
              const displayContent = (isLastStreaming && myStreamingText) ? myStreamingText : m.content;
              const stableKey = `msg-${i}`;

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