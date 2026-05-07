import React from "react";

interface ChatHeaderProps {
  workspace: string;
  sessionTitle: string;
  isSidebarOpen: boolean;
  setIsSidebarOpen: (val: boolean) => void;
  searchQuery: string;
  setSearchQuery: (val: string) => void;
  searchResults: number[];
  searchIndex: number;
  scrollToMatch: (index: number) => void;
  isSearchOpen: boolean;
  setIsSearchOpen: (val: boolean) => void;
}

export default function ChatHeader({
  workspace, sessionTitle, isSidebarOpen, setIsSidebarOpen,
  searchQuery, setSearchQuery, searchResults, searchIndex, scrollToMatch,
  isSearchOpen, setIsSearchOpen
}: ChatHeaderProps) {

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey) {
        scrollToMatch((searchIndex - 1 + searchResults.length) % searchResults.length);
      } else {
        scrollToMatch((searchIndex + 1) % searchResults.length);
      }
    }
  };

  const isCopilot = workspace?.toLowerCase().includes('copilot');

  return (
    <header className="flex items-center justify-between p-4 shrink-0 border-b border-[#333537]/30 bg-[#131314]/80 backdrop-blur-sm z-10 sticky top-0 gap-4">
       
       <div className="flex items-center gap-3 flex-1 min-w-0">
          {!isSidebarOpen && (
            <button onClick={() => setIsSidebarOpen(true)} className="p-2 hover:bg-[#282a2c] rounded-lg text-gray-400 transition-colors shrink-0">
               <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
            </button>
          )}
          
          <div className="flex flex-col justify-center min-w-0">
            <h1 className="text-[17px] text-[#e3e3e3] font-semibold tracking-wide truncate">
              {sessionTitle || 'New Diagnostic Chat'}
            </h1>
            
            <div className="flex flex-row items-center gap-2 mt-0.5 min-w-0">
              <span className="text-[11px] text-gray-500 font-medium tracking-wider uppercase shrink-0">
                DaiNamik Pryzm
              </span>
              
              <span className={`shrink-0 inline-flex items-center px-1.5 py-[2px] rounded text-[9px] leading-none font-bold uppercase tracking-wider border ${
                isCopilot
                  ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' 
                  : 'bg-orange-500/10 text-orange-400 border-orange-500/20'
              }`}>
                {isCopilot ? 'IT Copilot' : 'Personal'}
              </span>
            </div>
          </div>
       </div>

       <div className="flex items-center shrink-0">
          {isSearchOpen ? (
            <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center bg-[#1e1f20] border border-[#333537] rounded-lg px-2 h-9 transition-all shadow-xl z-20">
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
              {searchResults.length > 0 && (
                <span className="text-xs text-blue-400 font-mono mr-2 shrink-0">
                  {searchIndex + 1}/{searchResults.length}
                </span>
              )}
              <div className="flex items-center border-l border-[#333537] pl-1 h-full py-1 shrink-0">
                <button onClick={() => scrollToMatch((searchIndex - 1 + searchResults.length) % searchResults.length)} className="px-1.5 h-full hover:text-white text-gray-400 rounded transition-colors hover:bg-[#333537]" title="Previous">↑</button>
                <button onClick={() => scrollToMatch((searchIndex + 1) % searchResults.length)} className="px-1.5 h-full hover:text-white text-gray-400 rounded transition-colors hover:bg-[#333537]" title="Next">↓</button>
                <button onClick={() => { setIsSearchOpen(false); setSearchQuery(""); }} className="px-1.5 ml-1 h-full text-gray-500 hover:text-red-400 rounded transition-colors hover:bg-[#333537]">✕</button>
              </div>
            </div>
          ) : (
            <button onClick={() => setIsSearchOpen(true)} className="w-9 h-9 flex items-center justify-center hover:bg-[#282a2c] rounded-lg text-gray-400 transition-colors border border-transparent hover:border-[#333537]">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            </button>
          )}
       </div>
    </header>
  );
}