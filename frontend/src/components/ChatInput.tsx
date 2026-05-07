import React, { useRef, useState, useEffect } from "react";
import { FileUpload } from "@/hooks/useChatLogic";

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

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 200)}px`;
    }
  }, [prompt, inputRef]);

  const processFiles = (files: File[]) => {
    const validExts =[".txt", ".md", ".py", ".csv", ".json", ".log", ".yaml", ".yml", ".conf", ".ini"];
    
    const validFiles = files.filter(file => {
      const hasValidExt = validExts.some(ext => file.name.toLowerCase().endsWith(ext));
      const hasNoExt = !file.name.includes(".");
      return hasValidExt || hasNoExt || file.type.startsWith("text/");
    });

    const invalidFiles = files.filter(file => !validFiles.includes(file));

    const newValidUploads = validFiles.map((file) => ({
      id: Math.random().toString(36).substring(7), file, status: "pending" as const, progress: 0,
    }));

    const newInvalidUploads = invalidFiles.map((file) => ({
      id: Math.random().toString(36).substring(7), file, status: "error" as const, progress: 100, errorMessage: "Unsupported format"
    }));
    
    setUploads((prev) => [...prev, ...newValidUploads, ...newInvalidUploads]);
    if (newValidUploads.length > 0) processUploadQueue(newValidUploads);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(Array.from(e.target.files));
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setIsDragging(false);
    dragCounter.current = 0;
    if (!e.dataTransfer.files) return;
    processFiles(Array.from(e.dataTransfer.files));
  };

  return (
    <div className="w-full max-w-3xl relative">
      {uploads.length > 0 && (
      <div className="flex flex-wrap gap-2 mb-3">
          {uploads.map((u, i) => (
          <div key={i} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border ${
              u.status === "success" ? "bg-emerald-900/20 border-emerald-800 text-emerald-400" : 
              u.status === "error" ? "bg-red-900/20 border-red-800 text-red-400" : 
              "bg-[#1e1f20] border-[#333537] text-gray-300"
            }`}>
              
              {u.status === "uploading" ? (
                <svg className="w-3.5 h-3.5 animate-spin text-gray-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
              ) : u.status === "error" ? (
                <svg className="w-3.5 h-3.5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
              ) : (
                <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
              )}
              
              <span>{u.file.name}</span>
              {u.errorMessage && <span className="ml-1 opacity-80">({u.errorMessage})</span>}
              {(u.status === "success" || u.status === "error") && (
                <button type="button" onClick={() => setUploads(prev => prev.filter(up => up.id !== u.id))} className="ml-1 opacity-70 hover:opacity-100 hover:text-white transition-opacity">✕</button>
              )}
          </div>
          ))}
      </div>
      )}

      <div 
          className="relative bg-[#1e1f20] rounded-3xl transition-all duration-200 focus-within:bg-[#282a2c] shadow-lg border border-[#333537]/50"
          onDragEnter={(e) => { e.preventDefault(); dragCounter.current++; setIsDragging(true); }}
          onDragLeave={(e) => { e.preventDefault(); dragCounter.current--; if(dragCounter.current===0) setIsDragging(false); }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
      >
        {isDragging && (
            <div className="absolute inset-0 z-50 flex items-center justify-center bg-blue-500/10 backdrop-blur-sm rounded-3xl border-2 border-dashed border-blue-500 pointer-events-none">
              <span className="text-blue-400 font-bold flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>
                  Drop to upload
              </span>
            </div>
        )}

        <form onSubmit={handleInference} className="flex flex-col p-2">
            <textarea 
              ref={inputRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isAutoTesting}
              className="w-full bg-transparent px-4 pt-3 pb-2 text-[15px] text-[#e3e3e3] resize-none focus:outline-none custom-scrollbar min-h-[50px] max-h-[200px]"
              placeholder="Ask Pryzm anything..."
            />
            
            <div className="flex justify-between items-center px-2 pb-1">
                <div className="flex gap-1 items-center relative">
                    <input type="file" multiple className="hidden" ref={fileInputRef} onChange={handleFileSelect} />
                    <button 
                      type="button" 
                      onClick={() => fileInputRef.current?.click()}
                      className="p-2 rounded-full text-gray-400 hover:text-[#e3e3e3] hover:bg-[#333537] transition-colors"
                      title="Upload file"
                    >
                      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>
                    </button>

                    <button 
                      type="button" 
                      onClick={(e) => { e.stopPropagation(); isAutoTesting ? stopAutoTest() : setShowTestMenu(!showTestMenu); }} 
                      className={`p-2 rounded-full transition-colors ${isAutoTesting ? 'bg-red-500 text-white animate-pulse' : 'text-gray-500 hover:text-gray-300 hover:bg-[#333537]'}`} 
                      title={isAutoTesting ? "Stop Test" : "Debug Tools"}
                    >
                      {isAutoTesting ? <span className="text-sm">⏹</span> : (
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" /></svg>
                      )}
                    </button>
                    
                    {showTestMenu && !isAutoTesting && (
                      <div className="absolute bottom-[110%] left-8 mb-2 w-48 bg-[#282a2c] border border-[#333537] rounded-xl shadow-xl z-50 overflow-hidden flex flex-col py-1 animate-in fade-in slide-in-from-bottom-2">
                        <div className="px-3 py-1.5 border-b border-[#333537] mb-1">
                          <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Debug Scripts</span>
                        </div>
                        <button type="button" onClick={() => { setShowTestMenu(false); runTestSuite('it_demo'); }} className="text-left px-3 py-2 text-xs hover:bg-[#333537] text-gray-300">Run IT Demo</button>
                        <button type="button" onClick={() => { setShowTestMenu(false); runTestSuite('memory_test'); }} className="text-left px-3 py-2 text-xs hover:bg-[#333537] text-gray-300">Run Context Test</button>
                        <button type="button" onClick={() => { setShowTestMenu(false); runTestSuite('tool_chain'); }} className="text-left px-3 py-2 text-xs hover:bg-[#333537] text-gray-300">Run Tool Chain Test</button>
                      </div>
                    )}

                    <span className="text-[10px] text-gray-500 ml-2 font-mono select-none">~{totalTokens} / 8192</span>
                </div>
                
                {isProcessing ? (
                    <button type="button" onClick={stopAutoTest} className="p-2 bg-[#333537] hover:bg-red-500/80 rounded-full text-white flex items-center justify-center transition-colors">
                        <div className="w-3.5 h-3.5 bg-white rounded-sm"></div>
                    </button>
                ) : (
                    <button type="submit" disabled={!prompt.trim() || isAutoTesting} className="p-2 bg-[#e3e3e3] hover:bg-white disabled:bg-[#333537] disabled:text-gray-500 rounded-full text-black transition-colors">
                        <svg className="w-5 h-5 ml-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                    </button>
                )}
            </div>
        </form>
      </div>
    </div>
  );
}