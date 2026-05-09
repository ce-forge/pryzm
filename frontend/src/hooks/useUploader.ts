import { useState, useCallback } from "react";
import { FileUpload } from "@/types/chat";
import { APP_CONFIG } from "@/utils/constants";

export function useUploader(
  workspace: string,
  onSessionCreated: (id: string) => void
) {
  const [uploads, setUploads] = useState<FileUpload[]>([]);

  const processUploadQueue = async (filesToUpload: FileUpload[], currentSessionId: string | null) => {
    let activeId = currentSessionId;

    for (const item of filesToUpload) {
      setUploads((prev) => 
        prev.map((u) => (u.id === item.id ? { ...u, status: "uploading", progress: 50 } : u))
      );

      const formData = new FormData();
      formData.append("file", item.file);
      formData.append("workspace", workspace);
      if (activeId) formData.append("session_id", activeId);

      try {
        const res = await fetch(`${APP_CONFIG.API_URL}/upload`, { method: "POST", body: formData });
        if (res.ok) {
          const data = await res.json();
          setUploads((prev) => 
            prev.map((u) => (u.id === item.id ? { ...u, status: "success", progress: 100 } : u))
          );

          if (!activeId && data.session_id) {
            activeId = data.session_id;
            onSessionCreated(data.session_id);
          }
        } else {
            throw new Error("Rejected");
        }
      } catch (err) {
        setUploads((prev) => 
          prev.map((u) => (u.id === item.id ? { ...u, status: "error", progress: 0, errorMessage: "Failed" } : u))
        );
      }
    }
  };

  const clearQueue = useCallback(() => {
    setUploads((prev) => prev.filter((u) => u.status === 'uploading'));
  }, []);

  return { uploads, setUploads, processUploadQueue, clearQueue };
}