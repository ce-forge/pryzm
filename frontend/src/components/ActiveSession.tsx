"use client";

import React, { useRef, useEffect, useState, useCallback } from "react";
import { useSessionContext } from "@/context/SessionContext";
import { useInferenceContext } from "@/context/InferenceContext";
import { useUploaderContext } from "@/context/UploaderContext";
import { useTestSuiteContext } from "@/context/TestSuiteContext";
import { useWorkspaceContext } from "@/context/WorkspaceContext";
import { useMessageActions } from "@/hooks/useMessageActions";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useSearch } from "@/hooks/useSearch";
import { usePrompt } from "@/hooks/usePrompt";
import ChatInput from "./ChatInput";
import ChatHeader from "./ChatHeader";
import QuickActions from "./QuickActions";
import ProcessingAnimation from "./ProcessingAnimation";
import ThinkingPanel from "./ThinkingPanel";
import SearchBar from "./SearchBar";
import ChatTimestamp from "./ChatTimestamp";
import ChatBubble from "./ChatBubble";
import ConfirmModal from "./ConfirmModal";
import { Message } from "@/types/chat";

interface ActiveSessionProps {
  isSidebarOpen: boolean;
  setIsSidebarOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export default function ActiveSession({ isSidebarOpen, setIsSidebarOpen }: ActiveSessionProps) {
  const session = useSessionContext();
  const ai = useInferenceContext();
  const uploader = useUploaderContext();
  const tester = useTestSuiteContext();
  const { activeWorkspace, hasNoWorkspaces } = useWorkspaceContext();

  // Globe toggle is gated on the workspace having web_search in its
  // enabled_tools — Settings is the permission gate, the toggle is the
  // per-turn override.
  const webSearchAvailable = !!activeWorkspace?.enabled_tools?.includes("web_search");

  const messages = session.messages;
  const activeSessionKey = session.currentSession || "temp_new_chat";
  const myStreamingText = ai.streamingContent[activeSessionKey];
  const myStreamingReasoning = ai.streamingReasoning[activeSessionKey];

  const currentIsProcessing =
    session.streamingSessionIdsRef.current.has(activeSessionKey);
  const currentIsTesting = tester.activeTestSessions.has(activeSessionKey);

  const promptState = usePrompt(messages);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const { scrollRef, onScroll } = useAutoScroll({
    messages,
    streamingText: myStreamingText ?? "",
    isProcessing: currentIsProcessing,
  });
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; index: number } | null>(null);
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);

  useEffect(() => {
    const isDesktopPointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (textareaRef.current && activeSessionKey === "temp_new_chat" && isDesktopPointer) {
      textareaRef.current.focus();
    }
  }, [activeSessionKey]);

  const search = useSearch(messages, chatContainerRef);

  const handleInference = useCallback(
    async (rawPrompt: string) => {
      if (!rawPrompt.trim() || currentIsProcessing) return;

      let activeIdToUse = session.currentSession;
      if (activeIdToUse === "temp_new_chat") activeIdToUse = null;

      const pendingUploads = uploader.uploads.filter((u) => u.status === "pending");
      if (pendingUploads.length > 0) {
        await uploader.processUploadQueue(pendingUploads);
      }

      const successfulUploads = uploader.uploads.filter((u) => u.status === "success");
      const documentIds = successfulUploads
        .map((u) => u.document_id)
        .filter((id): id is string => Boolean(id));

      let attachedPrefix = successfulUploads
        .map((u) => `[Attached_File:${u.file.name}]`)
        .join("\n");
      if (attachedPrefix) attachedPrefix += "\n";

      const textToSend = attachedPrefix + rawPrompt;
      uploader.clearQueue();
      // Only ship the mode if the workspace permits it — defensive against
      // stale toggle state across workspace switches.
      const modes = (webSearchAvailable && webSearchEnabled) ? ["web_search"] : [];
      await ai.sendMessage(textToSend, activeIdToUse, documentIds, false, modes);
    },
    [currentIsProcessing, session.currentSession, uploader, ai, webSearchAvailable, webSearchEnabled],
  );

  const stopAllInference = useCallback(() => {
    tester.stopTestSuite(session.currentSession);
    ai.stopInference(session.currentSession);
  }, [tester, ai, session.currentSession]);

  const msgActions = useMessageActions(
    session.workspace,
    activeSessionKey,
    session.messages,
    session.replaceMessages,
    ai.sendMessage,
    session.navigateToSession,
    session.notifySessionCreated,
  );

  const onSubmit = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      const text = promptState.prompt.trim();
      if (!text || currentIsProcessing) return;
      handleInference(text);
      promptState.saveToHistory(text);
      promptState.setPrompt("");
    },
    [promptState, currentIsProcessing, handleInference],
  );

  const onDeleteRequest = useCallback(
    (id: string, idx: number) => setDeleteConfirm({ id, index: idx }),
    [],
  );

  if (hasNoWorkspaces) {
    return (
      <div className="flex flex-col flex-1 h-full w-full max-w-[100vw] overflow-hidden bg-[#131314]">
        <ChatHeader
          sessionTitle=""
          isSidebarOpen={isSidebarOpen}
          setIsSidebarOpen={setIsSidebarOpen}
        />
        <div className="flex-1 flex items-center justify-center px-6">
          <div className="max-w-md text-center text-sm text-gray-300 space-y-3">
            <h2 className="text-lg font-semibold">No workspaces yet</h2>
            <p className="text-gray-400">
              Your account has no workspaces, so there&apos;s nothing to chat
              with. Ask an admin to seed one for you, or create your own from
              the sidebar if your account is allowed to.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 h-full w-full max-w-[100vw] overflow-hidden bg-[#131314]">
      <ChatHeader
        sessionTitle={messages.length === 0 ? "" : session.sessionTitle}
        isSidebarOpen={isSidebarOpen}
        setIsSidebarOpen={setIsSidebarOpen}
        rightActions={<SearchBar {...search} />}
      />

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto overflow-x-hidden px-2 sm:px-4 py-2 custom-scrollbar w-full min-w-0"
      >
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

          {messages.map((m: Message, i: number) => {
            const isLastStreaming = currentIsProcessing && i === messages.length - 1 && m.role === "assistant";
            const liveToolCalls = isLastStreaming ? ai.streamingToolCalls[session.currentSession ?? ""] : undefined;
            const displayToolCalls = liveToolCalls ?? m.toolCalls;
            const displayContent = isLastStreaming && myStreamingText ? myStreamingText : m.content;
            const displayReasoning = isLastStreaming
              ? (myStreamingReasoning || undefined)
              : m.reasoningContent;
            const stableKey = m.id ?? `idx-${i}`;
            return (
              <React.Fragment key={stableKey}>
                <ChatTimestamp
                  timestamp={m.timestamp}
                  previousTimestamp={i > 0 ? messages[i - 1].timestamp : undefined}
                  isFirstMessage={i === 0}
                />
                <ChatBubble
                  message={m}
                  displayContent={displayContent}
                  displayReasoning={displayReasoning}
                  toolCalls={displayToolCalls}
                  index={i}
                  searchQuery={search.searchQuery}
                  isStreaming={isLastStreaming}
                  onDeleteRequest={onDeleteRequest}
                  saveEdit={msgActions.saveEdit}
                  branchSession={msgActions.branchSession}
                  rerunAssistant={msgActions.rerunAssistant}
                />
              </React.Fragment>
            );
          })}

          {currentIsProcessing && messages.length > 0 && !myStreamingText && (
            <>
              <ProcessingAnimation
                label={myStreamingReasoning ? "focusing…" : "reflecting…"}
              />
              {myStreamingReasoning && (
                <ThinkingPanel reasoning={myStreamingReasoning} variant="live" />
              )}
            </>
          )}
        </div>
      </div>

      <div className="shrink-0 pb-6 px-4 w-full flex justify-center bg-gradient-to-t from-[#131314] to-transparent">
        <ChatInput
          prompt={promptState.prompt}
          setPrompt={promptState.setPrompt}
          uploads={uploader.uploads}
          setUploads={uploader.setUploads}
          isProcessing={currentIsProcessing}
          isAutoTesting={currentIsTesting}
          handleInference={onSubmit}
          stopAutoTest={stopAllInference}
          handleKeyDown={(e) => promptState.handleKeyDown(e, onSubmit)}
          runTestSuite={(type) => tester.runTestSuite(type, session.currentSession)}
          processUploadQueue={(files) => uploader.processUploadQueue(files)}
          totalTokens={promptState.totalTokens}
          inputRef={textareaRef}
          webSearchAvailable={webSearchAvailable}
          webSearchEnabled={webSearchEnabled}
          setWebSearchEnabled={setWebSearchEnabled}
        />
      </div>

      <ConfirmModal
        isOpen={!!deleteConfirm}
        title="Delete Message?"
        description="This permanently removes the bubble from your history."
        onConfirm={() => {
          if (deleteConfirm) {
            msgActions.deleteMessage(deleteConfirm.id, deleteConfirm.index);
            setDeleteConfirm(null);
          }
        }}
        onCancel={() => setDeleteConfirm(null)}
      />
    </div>
  );
}
