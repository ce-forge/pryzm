import { useState, useCallback, useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
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
    xhr.withCredentials = true;
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

/**
 * Open an EventSource on /uploads/{document_id}/events and forward
 * terminal status into the upload pill.
 *
 * EventSource can't set custom Authorization headers — the token rides
 * in the URL as `?token=...`. This is the SSE-friendly fallback
 * documented in core/auth.py; the rest of the API still uses bearer
 * headers via apiFetch. Long-term endpoint is cookie auth.
 *
 * Closes on the first terminal event (`ready` or `error`) or on the
 * `onerror` callback. The browser does NOT need us to call .close()
 * for the connection to drop on page unload, but we do it anyway to
 * keep the open-connection count tight when many pills resolve in
 * quick succession.
 */
function subscribeToIngestionStatus(
  documentId: string,
  pillId: string,
  workspace: string,
  setUploads: Dispatch<SetStateAction<FileUpload[]>>,
): void {
  const token = getToken();
  const url = new URL(`${APP_CONFIG.API_URL}/uploads/${documentId}/events`);
  url.searchParams.set("workspace", workspace);
  if (token) url.searchParams.set("token", token);
  const es = new EventSource(url.toString(), { withCredentials: true });

  es.onmessage = (e) => {
    let payload: { status?: string; error?: string };
    try {
      payload = JSON.parse(e.data);
    } catch {
      return;
    }
    if (payload.status === "ready") {
      setUploads((prev) =>
        prev.map((u) =>
          u.id === pillId ? { ...u, status: "success" } : u,
        ),
      );
      es.close();
    } else if (payload.status === "error") {
      setUploads((prev) =>
        prev.map((u) =>
          u.id === pillId
            ? { ...u, status: "error", errorMessage: payload.error || "Processing failed" }
            : u,
        ),
      );
      es.close();
    }
  };

  es.onerror = () => {
    // Network blip or server hangup. We can't tell the user the doc
    // failed (it may still be processing) — surface a generic message
    // and let them re-attach if needed.
    setUploads((prev) =>
      prev.map((u) =>
        u.id === pillId && u.status === "processing"
          ? { ...u, status: "error", errorMessage: "Lost connection to server. Please re-attach the file." }
          : u,
      ),
    );
    es.close();
  };
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
          const documentId: string | undefined = data.document_id;
          // Hybrid UX: flip the pill to 'success' the moment the upload
          // XHR returns 202, even though analysis is still running
          // server-side. The pill FEELS instant — analysis runs in
          // the background, and the /analyze route waits for the
          // doc to be ready via the broker if the user sends a prompt
          // before analysis finishes (no auto-RAG miss). We still
          // open the SSE stream to catch terminal-error events from
          // the ingest pipeline, but 'ready' events are now a no-op
          // (pill is already green).
          setUploads((prev) =>
            prev.map((u) =>
              u.id === item.id
                ? {
                    ...u,
                    status: "success",
                    progress: 100,
                    document_id: documentId,
                  }
                : u,
            ),
          );
          if (documentId) {
            subscribeToIngestionStatus(documentId, item.id, workspace, setUploads);
          }
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
