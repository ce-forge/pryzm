import React from "react";

interface ChatTimestampProps {
  timestamp?: string;
  previousTimestamp?: string;
  isFirstMessage: boolean;
}

export const formatTimestamp = (timestamp?: string) => {
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

export default function ChatTimestamp({ timestamp, previousTimestamp, isFirstMessage }: ChatTimestampProps) {
  if (!timestamp) return null;

  let shouldShow = false;
  if (isFirstMessage) {
    shouldShow = true;
  } else if (previousTimestamp) {
    const diff = new Date(timestamp).getTime() - new Date(previousTimestamp).getTime();
    // Show timestamp if there is more than a 30-minute gap between messages
    if (diff > 30 * 60 * 1000) shouldShow = true; 
  }

  if (!shouldShow) return null;

  return (
    <div className="flex justify-center my-6 select-none">
      <span className="text-xs font-medium text-gray-500 bg-[#1e1f20] border border-[#333537] px-3 py-1 rounded-full">
        {formatTimestamp(timestamp)}
      </span>
    </div>
  );
}