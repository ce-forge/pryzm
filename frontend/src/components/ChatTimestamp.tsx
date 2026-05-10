import React from "react";

interface ChatTimestampProps {
  timestamp?: string;
  previousTimestamp?: string;
  isFirstMessage: boolean;
}

// Logic from your original file
export const formatTimestamp = (timestamp?: string) => {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  const now = new Date();
  
  // Calculate difference in days
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - (24 * 60 * 60 * 1000);
  const messageTime = date.getTime();

  const timeStr = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  
  if (messageTime >= startOfToday) return `Today ${timeStr}`;
  if (messageTime >= startOfYesterday) return `Yesterday ${timeStr}`;
  
  return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })} • ${timeStr}`;
};

export default function ChatTimestamp({ timestamp, previousTimestamp, isFirstMessage }: ChatTimestampProps) {
  if (!timestamp) return null;

  let shouldShow = false;
  if (isFirstMessage) {
    shouldShow = true;
  } else if (previousTimestamp) {
    const diff = new Date(timestamp).getTime() - new Date(previousTimestamp).getTime();
    // 30-minute gap logic
    if (diff > 30 * 60 * 1000) shouldShow = true; 
  }

  if (!shouldShow) return null;

  return (
    <div className="w-full flex justify-center my-10 relative select-none">
      {/* The Horizontal Line */}
      <div className="absolute inset-0 flex items-center">
        <div className="w-full border-t border-gray-800/40"></div>
      </div>
      
      {/* The Label */}
      <span className="relative text-[10px] font-bold text-gray-500 uppercase tracking-[0.2em] bg-[#131314] px-4">
        {formatTimestamp(timestamp)}
      </span>
    </div>
  );
}