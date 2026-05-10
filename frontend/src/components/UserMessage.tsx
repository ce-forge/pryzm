import React from "react";

interface UserMessageProps {
  content: string;
  searchQuery: string;
}

export default function UserMessage({ content, searchQuery }: UserMessageProps) {
  const attachmentRegex = /\[Attached_File:(.*?)\]/g;
  const attachments: string[] = [];
  let match;
  while ((match = attachmentRegex.exec(content)) !== null) attachments.push(match[1]);
  
  const cleanContent = content.replace(attachmentRegex, '').trim();

  // Handle Search Highlighting
  const renderText = () => {
    if (!searchQuery) return cleanContent;
    const escapedQuery = searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const parts = cleanContent.split(new RegExp(`(${escapedQuery})`, 'gi'));
    
    return parts.map((part, idx) => (
      part.toLowerCase() === searchQuery.toLowerCase() 
        ? <mark key={idx} className="search-match rounded-[3px] px-0.5 text-inherit transition-colors duration-200">{part}</mark>
        : part
    ));
  };

  return (
    <div className="flex flex-col items-end">
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2 justify-end">
          {attachments.map((f, i) => (
            <div key={i} className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-[#131314] text-gray-300 border border-[#333537]">
              <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
              {f}
            </div>
          ))}
        </div>
      )}
      <div className="whitespace-pre-wrap">{renderText()}</div>
    </div>
  );
}