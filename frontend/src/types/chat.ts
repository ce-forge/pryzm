export interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
  /** Image documents the auto-RAG path retrieved alongside this
   *  assistant turn. The frontend fetches each via GET /documents/{id}/raw
   *  and renders inline below the assistant prose. v1 lives only in the
   *  live-stream session state (state-only, not persisted across reload);
   *  a future schema change can persist this with the message row. */
  referencedFiles?: ReferencedFile[];
}

export interface ReferencedFile {
  id: string;
  filename: string;
  mime: string;
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