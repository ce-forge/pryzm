export interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
}

export interface FileUpload {
  id: string;
  file: File;
  status: "pending" | "uploading" | "success" | "error";
  progress: number;
  errorMessage?: string;
}