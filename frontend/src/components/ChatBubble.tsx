import React, { useState, useEffect, useRef } from "react";
import { useChatContext } from "@/context/ChatContext";
import { CheckIcon, CancelIcon, RerunIcon } from "./Icons";
import UserMessage from "./UserMessage";
import AssistantMessage from "./AssistantMessage";
import MessageActions from "./MessageActions";

interface ChatBubbleProps {
  message: any;
  index: number;
  activeSessionKey: string;
  searchQuery: string;
  isStreaming: boolean;
  onDeleteRequest: (id: string, index: number) => void;
}

export default function ChatBubble({ message, index, activeSessionKey, searchQuery, isStreaming, onDeleteRequest }: ChatBubbleProps) {
  const { msgActions } = useChatContext();
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(message.content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
                onClick={() => { msgActions.saveEdit(message.id, index, editValue, false); setIsEditing(false); }} 
                className="p-1.5 text-gray-500 hover:text-emerald-500 transition-colors" 
                title="Save changes"
            >
              <CheckIcon className="w-4 h-4" />
            </button>
            {message.role === 'user' && (
              <button 
                type="button"
                onClick={() => { msgActions.saveEdit(message.id, index, editValue, true); setIsEditing(false); }} 
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
        <div className={`flex flex-col ${message.role === 'user' ? 'max-w-[85%] items-end' : 'max-w-full items-start'}`}>
          <div className={`${message.role === 'user' ? 'bg-[#2f2f2f] text-[#e3e3e3] rounded-2xl py-2.5 px-5' : 'text-[#e3e3e3] px-1 w-full'}`}>
            {message.role === "user" ? (
              <UserMessage content={message.content} searchQuery={searchQuery} />
            ) : (
              <AssistantMessage content={message.content} searchQuery={searchQuery} />
            )}
          </div>

          {!isStreaming && (
            <MessageActions
              content={message.content}
              timestamp={message.timestamp}
              isUser={message.role === 'user'}
              onDelete={() => onDeleteRequest(message.id, index)}
              onEdit={() => { setIsEditing(true); setEditValue(message.content); }}
              onBranch={() => msgActions.branchSession(message.id)}
              onRerun={() => message.role === 'user' ? msgActions.saveEdit(message.id, index, message.content, true) : msgActions.rerunAssistant(index)}
            />
          )}
        </div>
      </div>
    </div>
  );
}