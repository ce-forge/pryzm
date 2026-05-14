import React, { useRef, useState, useEffect } from "react";
import { FileUpload } from "@/types/chat"; 
import { useOnClickOutside } from "@/hooks/useOnClickOutside";
import { APP_CONFIG } from "@/utils/constants";
import { PlusIcon, SendIcon, StopIcon, TerminalIcon, LoadingIcon, CancelIcon, DatabaseIcon } from "./Icons";

interface ChatInputProps {
  prompt: string;
  setPrompt: (p: string) => void;
  uploads: FileUpload[];
  setUploads: React.Dispatch<React.SetStateAction<FileUpload[]>>;
  isProcessing: boolean;
  isAutoTesting: boolean;
  handleInference: (e?: React.FormEvent) => void;
  stopAutoTest: () => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  runTestSuite: (type: "it_demo" | "memory_test" | "tool_chain") => void;
  processUploadQueue: (files: FileUpload[]) => void;
  totalTokens: number;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export default function ChatInput({
  prompt, setPrompt, uploads, setUploads, isProcessing, isAutoTesting,
  handleInference, stopAutoTest, handleKeyDown, runTestSuite,
  processUploadQueue, totalTokens, inputRef
}: ChatInputProps) {
  
  const [isDragging, setIsDragging] = useState(false);
  const [showTestMenu, setShowTestMenu] = useState(false);
  const dragCounter = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const menuWrapperRef = useRef<HTMLDivElement>(null);

  useOnClickOutside(menuWrapperRef, () => setShowTestMenu(false));

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 200)}px`;
    }
  }, [prompt, inputRef]);

  const processFiles = (files: File[]) => {
    const validExts = [".txt", ".md", ".py", ".csv", ".json", ".log", ".yaml", ".yml", ".conf", ".ini", ".jpg", ".jpeg", ".png", ".webp", ".pdf"];
    
    const mappedUploads = files.map(file => {
      const isSupported = validExts.some(ext => file.name.toLowerCase().endsWith(ext)) || !file.name.includes(".");
      return {
        id: Math.random().toString(36).substring(7),
        file,
        status: (isSupported ? "pending" : "error") as any,
        progress: isSupported ? 0 : 100,
        errorMessage: isSupported ? undefined : "Unsupported format"
      };
    });

    setUploads(prev => [...prev, ...mappedUploads]);
    const toUpload = mappedUploads.filter(u => u.status === "pending");
    if (toUpload.length > 0) processUploadQueue(toUpload);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setIsDragging(false); dragCounter.current = 0;
    if (e.dataTransfer.files) processFiles(Array.from(e.dataTransfer.files));
  };

  const removeUpload = (id: string) => setUploads(prev => prev.filter(up => up.id !== id));

  return (
    <div className="w-full max-w-3xl relative">
      {uploads.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
            {uploads.map((u) => (
              <div 
                key={u.id} 
                className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-[11px] font-medium border transition-all ${
                  u.status === 'success' ? 'bg-emerald-900/10 border-emerald-500/30 text-emerald-400' : 
                  u.status === 'error' ? 'bg-red-900/10 border-red-500/30 text-red-400' :
                  'bg-[#1e1f20] border-[#333537] text-gray-400'
                }`}
              >
                {u.status === "uploading" ? <LoadingIcon className="w-3.5 h-3.5" /> : <DatabaseIcon className="w-3.5 h-3.5" />}
                <span className="truncate max-w-[120px]">{u.file.name}</span>
                {u.errorMessage && <span className="opacity-60 text-[9px] uppercase font-bold ml-1">({u.errorMessage})</span>}
                <button onClick={() => removeUpload(u.id)} className="ml-1 hover:text-white transition-colors">
                  <CancelIcon className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
        </div>
      )}

      <div 
          className={`relative bg-[#1e1f20] rounded-[28px] transition-all duration-300 focus-within:bg-[#282a2c] border shadow-2xl ${isDragging ? 'border-blue-500 ring-4 ring-blue-500/10' : 'border-[#333537]/50'}`}
          onDragEnter={(e) => { e.preventDefault(); dragCounter.current++; setIsDragging(true); }}
          onDragLeave={(e) => { e.preventDefault(); dragCounter.current--; if(dragCounter.current===0) setIsDragging(false); }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
      >
        <form onSubmit={handleInference} className="flex flex-col p-2">
            <textarea 
              ref={inputRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isAutoTesting}
              className="w-full bg-transparent px-4 pt-3 pb-2 text-[15px] text-[#e3e3e3] resize-none focus:outline-none custom-scrollbar min-h-[52px] max-h-[200px] leading-relaxed"
              placeholder="Ask Pryzm anything..."
            />
            
            <div className="flex justify-between items-center px-2 pb-1">
                <div className="flex gap-1 items-center relative" ref={menuWrapperRef}>
                    {/* Single hidden input with a wildcard accept. JS-side
                        validation in processFiles (validExts) still rejects
                        unsupported types with an error pill. Loose accept is
                        what consistently surfaces Camera + Gallery + Files
                        in the native picker across Samsung Internet, Chrome
                        on Android 14/15, GNOME, KDE, macOS, Windows. */}
                    <input
                      type="file"
                      multiple
                      className="hidden"
                      ref={fileInputRef}
                      accept="*/*"
                      onChange={(e) => e.target.files && processFiles(Array.from(e.target.files))}
                    />

                    <button type="button" onClick={() => fileInputRef.current?.click()}
                      aria-label="Attach file"
                      className="p-2.5 rounded-full text-gray-500 hover:text-[#e3e3e3] hover:bg-[#333537] transition-all">
                      <PlusIcon className="w-5 h-5" />
                    </button>

                    <button type="button" onClick={(e) => { e.stopPropagation(); isAutoTesting ? stopAutoTest() : setShowTestMenu(!showTestMenu); }}
                      className={`p-2.5 rounded-full transition-all ${isAutoTesting ? 'bg-red-500 text-white animate-pulse' : 'text-gray-500 hover:bg-[#333537]'}`}>
                      {isAutoTesting ? <StopIcon className="w-4 h-4 fill-white" /> : <TerminalIcon className="w-4 h-4" />}
                    </button>

                    {showTestMenu && !isAutoTesting && (
                      <div className="absolute bottom-[110%] left-0 mb-2 w-48 bg-[#282a2c] border border-[#333537] rounded-2xl shadow-2xl z-50 py-2 overflow-hidden animate-in fade-in slide-in-from-bottom-2">
                        <div className="px-4 py-1 text-[10px] font-bold text-gray-500 uppercase tracking-widest border-b border-white/5 mb-1">Diagnostics</div>
                        <button type="button" onClick={() => { setShowTestMenu(false); runTestSuite('it_demo'); }} className="w-full text-left px-4 py-2 text-xs hover:bg-[#333537] text-gray-300 transition-colors">Run IT Demo</button>
                        <button type="button" onClick={() => { setShowTestMenu(false); runTestSuite('memory_test'); }} className="w-full text-left px-4 py-2 text-xs hover:bg-[#333537] text-gray-300 transition-colors">Run Context Test</button>
                        <button type="button" onClick={() => { setShowTestMenu(false); runTestSuite('tool_chain'); }} className="w-full text-left px-4 py-2 text-xs hover:bg-[#333537] text-gray-300 transition-colors">Run Tool Chain</button>
                      </div>
                    )}

                    <span className="text-[10px] text-gray-600 ml-2 font-mono select-none">~{totalTokens} / {APP_CONFIG.VISIBLE_TOKEN_LIMIT}</span>
                </div>
                
                <div className="flex items-center">
                  {isProcessing ? (
                      <button type="button" onClick={(e) => { e.preventDefault(); stopAutoTest(); }} className="p-2 bg-[#333537] hover:bg-red-500/80 rounded-full text-white transition-colors">
                          <StopIcon className="w-5 h-5 fill-white" />
                      </button>
                  ) : (
                      <button type="submit" disabled={!prompt.trim() || isAutoTesting} 
                        className="p-2.5 bg-[#e3e3e3] hover:bg-white disabled:bg-[#333537] disabled:text-gray-600 rounded-full text-black transition-all active:scale-95 shadow-lg">
                          <SendIcon className="w-5 h-5 ml-0.5" />
                      </button>
                  )}
                </div>
            </div>
        </form>
      </div>
    </div>
  );
}