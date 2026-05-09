import React from "react";

interface SearchBarProps {
  searchQuery: string;
  setSearchQuery: (val: string) => void;
  totalMatches: number;
  searchIndex: number;
  scrollToMatch: (index: number) => void;
  isSearchOpen: boolean;
  setIsSearchOpen: (val: boolean) => void;
}

export default function SearchBar({
  searchQuery, setSearchQuery, totalMatches, searchIndex, scrollToMatch, isSearchOpen, setIsSearchOpen
}: SearchBarProps) {

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey) {
        scrollToMatch((searchIndex - 1 + totalMatches) % totalMatches);
      } else {
        scrollToMatch((searchIndex + 1) % totalMatches);
      }
    }
  };

  if (!isSearchOpen) {
    return (
      <button onClick={() => setIsSearchOpen(true)} className="w-9 h-9 flex items-center justify-center hover:bg-[#282a2c] rounded-lg text-gray-400 transition-colors border border-transparent hover:border-[#333537]">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
      </button>
    );
  }

  return (
    <div className="relative flex items-center bg-[#1e1f20] border border-[#333537] rounded-lg px-2 h-9 transition-all shadow-xl z-20">
      <svg className="w-3.5 h-3.5 text-gray-500 ml-1 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
      <input 
        autoFocus
        type="text" 
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Search logs..." 
        className="bg-transparent text-sm text-[#e3e3e3] outline-none w-32 md:w-48 px-2"
      />
      {totalMatches > 0 && (
        <span className="text-xs text-blue-400 font-mono mr-2 shrink-0">
          {searchIndex + 1}/{totalMatches}
        </span>
      )}
      <div className="flex items-center border-l border-[#333537] pl-1 h-full py-1 shrink-0">
        <button onClick={() => scrollToMatch((searchIndex - 1 + totalMatches) % totalMatches)} className="px-1.5 h-full hover:text-white text-gray-400 rounded transition-colors hover:bg-[#333537]" title="Previous">↑</button>
        <button onClick={() => scrollToMatch((searchIndex + 1) % totalMatches)} className="px-1.5 h-full hover:text-white text-gray-400 rounded transition-colors hover:bg-[#333537]" title="Next">↓</button>
        <button onClick={() => { setIsSearchOpen(false); setSearchQuery(""); }} className="px-1.5 ml-1 h-full text-gray-500 hover:text-red-400 rounded transition-colors hover:bg-[#333537]">✕</button>
      </div>
    </div>
  );
}