// src/components/MessageActions.tsx
import React, { useState } from "react";
import { CopyIcon, CheckIcon, EditIcon, RerunIcon, BranchIcon, TrashIcon, ThumbsDownIcon } from "./Icons";

interface MessageActionsProps {
  content: string;
  timestamp?: string;
  onEdit: () => void;
  onDelete: () => void;
  onRerun?: () => void;
  onBranch: () => void;
  onThumbsDown?: () => Promise<void> | void;
  isUser: boolean;
}

export default function MessageActions({ content, timestamp, onEdit, onDelete, onRerun, onBranch, onThumbsDown, isUser }: MessageActionsProps) {
  const [copied, setCopied] = useState(false);
  const [reported, setReported] = useState(false);

  const copyToClipboard = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(content);
      } else {
        // Fallback for mobile/non-HTTPS
        const textArea = document.createElement("textarea");
        textArea.value = content;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Copy failed", err);
    }
  };

  const reportThumbsDown = async () => {
    if (!onThumbsDown || reported) return;
    try {
      await onThumbsDown();
      setReported(true);
    } catch (err) {
      console.error("Thumbs-down submit failed", err);
    }
  };

  const btnClass = "p-1.5 rounded-md text-gray-500 hover:bg-[#2f2f2f] hover:text-[#e3e3e3] transition-all duration-200";

  return (
    <div className={`flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity duration-200 pointer-events-none group-hover:pointer-events-auto [@media(hover:none)]:pointer-events-auto ${isUser ? 'justify-end' : 'justify-start'}`}>

      {/* Claude Style Timestamp: Next to buttons */}
      {timestamp && (
        <span className="text-[10px] text-gray-600 mr-2 select-none">
          {new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      )}

      <button onClick={copyToClipboard} className={btnClass}>
        {copied ? <CheckIcon className="w-3.5 h-3.5" /> : <CopyIcon className="w-3.5 h-3.5" />}
      </button>

      {onThumbsDown && (
        <button
          onClick={reportThumbsDown}
          className={`${btnClass} ${reported ? "text-red-400 hover:text-red-400" : ""}`}
          title={reported ? "Reported" : "Flag this reply for the admin"}
          aria-label={reported ? "Reply reported" : "Flag this reply"}
          aria-pressed={reported}
        >
          <ThumbsDownIcon
            className="w-3.5 h-3.5"
            fill={reported ? "currentColor" : "none"}
          />
        </button>
      )}

      {isUser && (
        <button onClick={onEdit} className={btnClass}>
          <EditIcon className="w-3.5 h-3.5" />
        </button>
      )}

      {onRerun && (
        <button onClick={onRerun} className={btnClass}>
          <RerunIcon className="w-3.5 h-3.5" />
        </button>
      )}

      <button onClick={onBranch} className={btnClass}>
        <BranchIcon className="w-3.5 h-3.5" />
      </button>

      <button onClick={onDelete} className={btnClass}>
        <TrashIcon className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
