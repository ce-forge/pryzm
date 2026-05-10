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
import AssistantMessage from "./AssistantMessage";
import ConfirmModal from "./ConfirmModal"; // NEW IMPORT

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
    if (currentIsProcessing && myStreamingText) scrollToBottom();
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
    <div className="flex flex-col flex-1 h-full bg-[#131314]">
      <ChatHeader workspace={session.workspace} sessionTitle={session.sessionTitle} isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} rightActions={<SearchBar {...search} />} />
      
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-2 custom-scrollbar">
        <div ref={chatContainerRef} className="w-full max-w-3xl mx-auto flex flex-col min-h-full">
            
            {messages.length === 0 && !session.isInitialLoading && !currentIsProcessing && (
              <QuickActions setPrompt={promptState.setPrompt} inputRef={textareaRef} />
            )}

            {messages.map((m: any, i: number) => {
              const isLastStreaming = currentIsProcessing && i === messages.length - 1 && m.role === "assistant";
              if (isLastStreaming) return (
                <div key="stream" className="w-full mb-8"><AssistantMessage content={myStreamingText || m.content} searchQuery={search.searchQuery} /></div>
              );

              return (
                <React.Fragment key={m.id || i}>
                  <ChatTimestamp timestamp={m.timestamp} previousTimestamp={i > 0 ? messages[i-1].timestamp : undefined} isFirstMessage={i === 0} />
                  <ChatBubble message={m} index={i} activeSessionKey={activeSessionKey} searchQuery={search.searchQuery} isStreaming={currentIsProcessing} onDeleteRequest={(id, idx) => setDeleteConfirm({ id, index: idx })} />
                </React.Fragment>
              );
            })}
            
            {currentIsProcessing && messages.length > 0 && !myStreamingText && <ProcessingAnimation />}
         </div>
      </div>

      <div className="shrink-0 pb-6 px-4 bg-gradient-to-t from-[#131314] to-transparent">
        <ChatInput 
            prompt={promptState.prompt} setPrompt={promptState.setPrompt} uploads={uploader.uploads} setUploads={uploader.setUploads}
            isProcessing={currentIsProcessing} isAutoTesting={currentIsTesting} handleInference={onSubmit} stopAutoTest={stopAllInference}
            handleKeyDown={(e: any) => promptState.handleKeyDown(e, onSubmit)} 
            runTestSuite={(type: any) => tester.runTestSuite(type, session.currentSession)}
            processUploadQueue={(files: any[]) => uploader.processUploadQueue(files)} 
            totalTokens={promptState.totalTokens} inputRef={textareaRef}
        />
      </div>

      {/* SWAPPED TO THE NEW COMPONENT */}
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