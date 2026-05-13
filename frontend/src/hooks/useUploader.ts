import { useState, useCallback } from "react";
import { FileUpload } from "@/types/chat";
import { apiFetch } from "@/utils/apiClient";

export function useUploader(workspace: string) {
  const [uploads, setUploads] = useState<FileUpload[]>([]);

  const processUploadQueue = async (filesToUpload: FileUpload[]) => {
    for (const item of filesToUpload) {
      
      setUploads((prev) =>
        prev.map((u) =>
          u.id === item.id
            ? { ...u, status: "uploading", progress: 50 }
            : u
        )
      );

      const formData = new FormData();
      formData.append("file", item.file);
      formData.append("workspace", workspace);

      try {
        const res = await apiFetch("/upload", {
          method: "POST",
          body: formData,
        });

        if (res.ok) {
          const data = await res.json();
          
          setUploads((prev) =>
            prev.map((u) =>
              u.id === item.id
                ? {
                    ...u,
                    status: "success",
                    progress: 100,
                    document_id: data.details?.document_id,
                  }
                : u
            )
          );
        } else {
          throw new Error("Upload failed");
        }
      } catch (err) {
        
        setUploads((prev) =>
          prev.map((u) =>
            u.id === item.id
              ? { ...u, status: "error", errorMessage: "Failed" }
              : u
          )
        );
      }
    }
  };

  const clearQueue = useCallback(() => setUploads([]), []);

  return { uploads, setUploads, processUploadQueue, clearQueue };
}