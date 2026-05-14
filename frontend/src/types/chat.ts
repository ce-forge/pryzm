export interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
}

export interface FileUpload {
  id: string;
  document_id?: string;
  file: File;
  status: "pending" | "uploading" | "success" | "error";
  /** 0..100 percentage of bytes sent. Hits 100 the moment the XHR
   *  upload completes, but the pill stays in "uploading" until the
   *  server response arrives (the gap is backend processing). The
   *  progress ring renders an indeterminate spin during that window. */
  progress: number;
  /** blob URL (URL.createObjectURL) for image-MIME uploads, used to
   *  render a thumbnail in the pill. Revoke on remove/unmount. */
  previewUrl?: string;
  errorMessage?: string;
}