import { useState, useCallback, useEffect } from "react";
import { FileUpload } from "@/types/chat";
import { APP_CONFIG } from "@/utils/constants";
import { getToken } from "@/utils/apiClient";

/**
 * Upload a single file via XMLHttpRequest so the caller gets real
 * progress events. fetch() doesn't expose upload-progress in a
 * cross-browser way (ReadableStream upload bodies are Chrome 105+
 * only, Safari unsupported). XHR has done this consistently since
 * forever.
 *
 * `apiFetch`'s wrapper is NOT used here — it's fetch-based. The auth
 * header injection is duplicated below to keep XHR scoped to this one
 * call site rather than reshape the wider API client.
 */
function uploadWithProgress(
  file: File,
  workspace: string,
  onProgress: (pct: number) => void,
): Promise<{ ok: boolean; status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("workspace", workspace);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${APP_CONFIG.API_URL}/upload`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });
    xhr.onload = () =>
      resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, body: xhr.responseText });
    xhr.onerror = () => reject(new Error("Network error"));
    xhr.onabort = () => reject(new Error("Aborted"));
    xhr.send(form);
  });
}

export function useUploader(workspace: string) {
  const [uploads, setUploads] = useState<FileUpload[]>([]);

  // Clean up blob URLs on unmount so image previews don't leak.
  useEffect(() => {
    return () => {
      for (const u of uploads) {
        if (u.previewUrl) URL.revokeObjectURL(u.previewUrl);
      }
    };
    // We intentionally only revoke on unmount, not every state change —
    // pills that survive a re-render keep their preview URL alive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const processUploadQueue = async (filesToUpload: FileUpload[]) => {
    for (const item of filesToUpload) {
      setUploads((prev) =>
        prev.map((u) => (u.id === item.id ? { ...u, status: "uploading", progress: 0 } : u)),
      );

      try {
        const res = await uploadWithProgress(item.file, workspace, (pct) => {
          setUploads((prev) =>
            prev.map((u) => (u.id === item.id ? { ...u, progress: pct } : u)),
          );
        });

        if (res.ok) {
          const data = JSON.parse(res.body);
          setUploads((prev) =>
            prev.map((u) =>
              u.id === item.id
                ? {
                    ...u,
                    status: "success",
                    progress: 100,
                    document_id: data.details?.document_id,
                  }
                : u,
            ),
          );
        } else {
          // Try to surface the server's detail message rather than a
          // generic "Failed" — the user has been seeing 422/400 with
          // specific reasons (e.g. "No extractable text").
          let detail = "Failed";
          try {
            const parsed = JSON.parse(res.body);
            if (typeof parsed?.detail === "string") detail = parsed.detail;
          } catch {
            /* leave detail as "Failed" */
          }
          setUploads((prev) =>
            prev.map((u) =>
              u.id === item.id ? { ...u, status: "error", errorMessage: detail } : u,
            ),
          );
        }
      } catch {
        setUploads((prev) =>
          prev.map((u) =>
            u.id === item.id ? { ...u, status: "error", errorMessage: "Failed" } : u,
          ),
        );
      }
    }
  };

  const clearQueue = useCallback(() => {
    setUploads((prev) => {
      for (const u of prev) {
        if (u.previewUrl) URL.revokeObjectURL(u.previewUrl);
      }
      return [];
    });
  }, []);

  return { uploads, setUploads, processUploadQueue, clearQueue };
}
