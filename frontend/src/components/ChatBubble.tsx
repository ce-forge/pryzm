import React, { useState, useEffect, useRef } from "react";
import { CheckIcon, CancelIcon, RerunIcon } from "./Icons";
import UserMessage from "./UserMessage";
import AssistantMessage from "./AssistantMessage";
import MessageActions from "./MessageActions";
import ToolCallsBlock from "./ToolCallsBlock";
import type { ToolCall } from "@/types/chat";

interface ChatBubbleProps {
  // stable identity (parent passes `m` directly, no spread). The shape
  // here is the message row from useSession's messageCache — we leave
  // it loosely typed to avoid coupling this component to the entire
  // server-message schema.
  message: { id?: string; role: string; content: string; timestamp?: string; toolCalls?: ToolCall[] };
  displayContent: string; // streamed text; updates per token without changing `message`
  index: number;
  searchQuery: string;
  isStreaming: boolean;
  onDeleteRequest: (id: string, index: number) => void;
  saveEdit: (msgId: string | undefined, index: number, newContent: string, rerun: boolean) => void;
  branchSession: (msgId: string) => void;
  rerunAssistant: (index: number) => void;
}

function ChatBubbleImpl({
  message,
  displayContent,
  index,
  searchQuery,
  isStreaming,
  onDeleteRequest,
  saveEdit,
  branchSession,
  rerunAssistant,
}: ChatBubbleProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(message.content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Reset the edit buffer whenever the underlying message identity or
  // content changes — keeps the textarea in sync with the source when
  // the user toggles edit mode on/off across re-renders.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!isEditing) setEditValue(message.content);
  }, [message.id, message.content, isEditing]);

  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [editValue, isEditing]);

  if (isEditing) {
    return (
      <div className="flex justify-end w-full mb-6">
        <div className="w-full max-w-[85%] bg-[#2f2f2f] text-[#e3e3e3] rounded-2xl py-3 px-5 border border-white/5 shadow-xl transition-all">
          <textarea
            ref={textareaRef}
            autoFocus
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            className="w-full bg-transparent text-[15px] resize-none outline-none leading-relaxed overflow-hidden"
          />
          <div className="flex justify-end items-center gap-2 mt-2 pt-2 border-t border-white/5">
            <button
              type="button"
              onClick={() => setIsEditing(false)}
              className="p-1.5 text-gray-500 hover:text-red-500 transition-colors"
              title="Cancel"
            >
              <CancelIcon className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => { saveEdit(message.id, index, editValue, false); setIsEditing(false); }}
              className="p-1.5 text-gray-500 hover:text-emerald-500 transition-colors"
              title="Save changes"
            >
              <CheckIcon className="w-4 h-4" />
            </button>
            {message.role === 'user' && (
              <button
                type="button"
                onClick={() => { saveEdit(message.id, index, editValue, true); setIsEditing(false); }}
                className="flex items-center gap-1.5 pl-2 pr-1 py-1.5 group/rerun transition-all"
              >
                <RerunIcon className="w-3.5 h-3.5 text-gray-500 group-hover/rerun:text-blue-400 group-hover/rerun:rotate-45 transition-all duration-300" />
                <span className="text-[10px] font-bold tracking-tighter text-gray-500 group-hover/rerun:text-blue-400">RERUN</span>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex flex-col w-full mb-6 relative">
      <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} w-full`}>
        <div className={`flex flex-col ${message.role === 'user' ? 'max-w-[85%] items-end' : 'w-full items-start'} min-w-0`}>
          <div className={`${message.role === 'user' ? 'bg-[#2f2f2f] text-[#e3e3e3] rounded-2xl py-2.5 px-5' : 'text-[#e3e3e3] px-1 w-full flex-1'} break-words min-w-0`}>
            {message.role === "user" ? (
              <UserMessage content={displayContent} searchQuery={searchQuery} />
            ) : (
              <AssistantMessage content={displayContent} searchQuery={searchQuery} />
            )}
          </div>

          {/* Structured tool calls — engine-emitted, persisted on the
              messages.tool_calls JSONB column. Only renders on assistant
              turns that actually executed tools. */}
          {message.role !== "user" && message.toolCalls && message.toolCalls.length > 0 && (
            <ToolCallsBlock calls={message.toolCalls} />
          )}

          {!isStreaming && (
            <MessageActions
              content={displayContent}
              timestamp={message.timestamp}
              isUser={message.role === 'user'}
              onDelete={() => onDeleteRequest(message.id!, index)}
              onEdit={() => { setIsEditing(true); setEditValue(message.content); }}
              onBranch={() => branchSession(message.id!)}
              onRerun={() => message.role === 'user'
                ? saveEdit(message.id, index, message.content, true)
                : rerunAssistant(index)
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}

const ChatBubble = React.memo(ChatBubbleImpl, (prev, next) => {
  // Stable bubbles only re-render when their own message identity, displayed
  // content, search highlight, or streaming flag changes. Callback props are
  // assumed stabilized by useCallback at the parent.
  return (
    prev.message === next.message &&
    prev.displayContent === next.displayContent &&
    prev.searchQuery === next.searchQuery &&
    prev.isStreaming === next.isStreaming &&
    prev.index === next.index
  );
});

export default ChatBubble;
