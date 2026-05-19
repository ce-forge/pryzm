export interface ReferencedFile {
  id: string;
  filename: string;
  mime: string;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: string;
}

export interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
  referencedFiles?: ReferencedFile[];
  toolCalls?: ToolCall[];
  /** Reasoning_content from thinking-mode models. Empty/undefined renders no panel. */
  reasoningContent?: string;
  /** Wall-clock duration of the reasoning phase, in seconds. */
  reasoningDurationS?: number | null;
}

export interface FileUpload {
  id: string;
  document_id?: string;
  file: File;
  status: "pending" | "uploading" | "processing" | "success" | "error";
  /** 0..100 percentage of bytes sent. Hits 100 the moment the XHR
   *  upload completes; the pill then transitions to "processing" while
   *  the backend captions/extracts/embeds the document. The pill stays
   *  in "processing" until the SSE stream reports a terminal status
   *  ("ready" → "success" or "error"). The progress ring renders an
   *  indeterminate spin during the processing window. */
  progress: number;
  /** blob URL (URL.createObjectURL) for image-MIME uploads, used to
   *  render a thumbnail in the pill. Revoke on remove/unmount. */
  previewUrl?: string;
  errorMessage?: string;
}