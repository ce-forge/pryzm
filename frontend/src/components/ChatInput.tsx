import React, { useRef, useState, useEffect } from "react";
import { FileUpload } from "@/types/chat";
import { useOnClickOutside } from "@/hooks/useOnClickOutside";
import { APP_CONFIG } from "@/utils/constants";
import { apiFetch } from "@/utils/apiClient";
import { PlusIcon, SendIcon, StopIcon, TerminalIcon, CancelIcon, DatabaseIcon, AlertIcon } from "./Icons";
import { CircularProgress } from "./CircularProgress";

/** Hash-style names from Samsung's SAF temp camera captures (32-char
 *  hex with no separators) propagate as-is through the upload pipeline
 *  — pill, FormData, Document.filename, [Attached_File:] marker, and
 *  the File Analyzed widget all show the full hash, which is noise.
 *
 *  Detect that shape and replace it with the first 8 chars so every
 *  downstream surface sees the short name. We rewrap as a new File
 *  (.name is read-only) preserving type + lastModified so the upload
 *  payload is identical apart from the filename.
 *
 *  Names with separators (IMG_20240515_…, vacation_paris.jpg) or
 *  short bases pass through untouched — those carry meaning. */
function shortenIfHashName(file: File): File {
  const dot = file.name.lastIndexOf(".");
  const base = dot === -1 ? file.name : file.name.slice(0, dot);
  const ext = dot === -1 ? "" : file.name.slice(dot);
  if (base.length < 16 || !/^[a-zA-Z0-9]+$/.test(base)) {
    return file;
  }
  return new File([file], `${base.slice(0, 8)}${ext}`, {
    type: file.type,
    lastModified: file.lastModified,
  });
}

/** Fallback truncation for *legitimate* long filenames (e.g. a user
 *  uploaded "my_very_long_descriptive_vacation_photo.jpg"). Hash names
 *  are already short by the time they reach the pill thanks to
 *  shortenIfHashName, so this rarely fires now. Kept as defensive
 *  display layer. */
function shortDisplayName(name: string): string {
  const dot = name.lastIndexOf(".");
  const base = dot === -1 ? name : name.slice(0, dot);
  const ext = dot === -1 ? "" : name.slice(dot);
  if (base.length <= 12) return name;
  return `${base.slice(0, 8)}…${ext}`;
}

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

  // Block send while any attached file is still being prepared. Without
  // this gate the prompt goes out with an [Attached_File:foo.jpg] marker
  // but the chunks aren't in the DB yet, the auto-RAG path misses them,
  // and the user gets a worse answer than if they'd waited. Covers:
  // - 'pending' (queued client-side, not started),
  // - 'uploading' (XHR in flight),
  // - 'processing' (bytes on server, captioning/embedding in progress).
  const uploadsInProgress = uploads.some(
    (u) => u.status === "pending" || u.status === "uploading" || u.status === "processing",
  );

  const guardedSubmit = (e?: React.FormEvent) => {
    if (uploadsInProgress) {
      e?.preventDefault();
      return;
    }
    handleInference(e);
  };

  const guardedKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (uploadsInProgress && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      return;
    }
    handleKeyDown(e);
  };

  const processFiles = (rawFiles: File[]) => {
    const validExts = [".txt", ".md", ".py", ".csv", ".json", ".log", ".yaml", ".yml", ".conf", ".ini", ".jpg", ".jpeg", ".png", ".webp", ".pdf"];

    const mappedUploads = rawFiles.map(rawFile => {
      // Rename Samsung's hash-style camera captures before anything
      // downstream sees the file. The short name then propagates
      // through pill, FormData, Document.filename, and the marker.
      const file = shortenIfHashName(rawFile);
      const isSupported = validExts.some(ext => file.name.toLowerCase().endsWith(ext)) || !file.name.includes(".");
      // Mint a blob URL for image MIMEs so the pill can render a real
      // thumbnail. Revoked on remove / clear / unmount in useUploader.
      const previewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
      return {
        id: Math.random().toString(36).substring(7),
        file,
        status: (isSupported ? "pending" : "error") as FileUpload["status"],
        progress: isSupported ? 0 : 100,
        previewUrl,
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

  const removeUpload = (id: string) => setUploads(prev => {
    const removed = prev.find(up => up.id === id);
    if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
    // If the upload completed on the server, free the Document row +
    // chunks + on-disk bytes server-side. Without this, cancelled
    // pre-send uploads stay orphaned in the workspace forever.
    // Fire-and-forget; if the request fails the orphan is non-fatal.
    if (removed?.document_id) {
      apiFetch(`/documents/${removed.document_id}`, { method: "DELETE" })
        .catch(() => {});
    }
    return prev.filter(up => up.id !== id);
  });

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
                <div className="relative w-7 h-7 shrink-0">
                  {u.previewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element -- data: URLs don't work with next/Image without a custom loader
                    <img
                      src={u.previewUrl}
                      alt=""
                      className="w-7 h-7 object-cover rounded"
                    />
                  ) : (
                    <DatabaseIcon className="w-7 h-7 p-1" />
                  )}
                  {(u.status === "uploading" || u.status === "processing") && (
                    <span className="absolute inset-0 bg-black/40 rounded flex items-center justify-center">
                      <CircularProgress
                        value={u.status === "processing" ? 100 : u.progress}
                        className="w-6 h-6"
                      />
                    </span>
                  )}
                  {u.status === "error" && (
                    <span className="absolute inset-0 bg-black/40 rounded flex items-center justify-center">
                      <AlertIcon className="w-4 h-4" />
                    </span>
                  )}
                </div>
                <span className="truncate max-w-[120px]">{shortDisplayName(u.file.name)}</span>
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
        <form onSubmit={guardedSubmit} className="flex flex-col p-2">
            <textarea
              ref={inputRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={guardedKeyDown}
              disabled={isAutoTesting}
              className="w-full bg-transparent px-4 pt-3 pb-2 text-[15px] text-[#e3e3e3] resize-none focus:outline-none custom-scrollbar min-h-[52px] max-h-[200px] leading-relaxed"
              placeholder="Ask Pryzm anything..."
            />
            
            <div className="flex justify-between items-center px-2 pb-1">
                <div className="flex gap-1 items-center relative" ref={menuWrapperRef}>
                    {/* Explicit image MIME list. Samsung Internet's picker
                        only surfaces Gallery (Photos) as a top-level entry
                        when accept enumerates image types specifically; a
                        wildcard or mixed accept buries Gallery under the
                        SAF chooser. The trade-off is that text/PDF uploads
                        via the picker are dropped — those still work
                        through drag-and-drop on desktop (handleDrop calls
                        processFiles directly, bypassing this filter). */}
                    <input
                      type="file"
                      multiple
                      className="hidden"
                      ref={fileInputRef}
                      accept="image/jpeg, image/png, image/webp"
                      onChange={(e) => e.target.files && processFiles(Array.from(e.target.files))}
                    />

                    <button type="button" onClick={() => fileInputRef.current?.click()}
                      aria-label="Attach file"
                      className="p-2.5 rounded-full text-gray-500 hover:text-[#e3e3e3] hover:bg-[#333537] transition-all">
                      <PlusIcon className="w-5 h-5" />
                    </button>

                    <button type="button" onClick={(e) => {
                        e.stopPropagation();
                        if (isAutoTesting) stopAutoTest();
                        else setShowTestMenu(!showTestMenu);
                      }}
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
                      <button type="submit" disabled={!prompt.trim() || isAutoTesting || uploadsInProgress}
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