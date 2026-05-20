import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

export type DownloadStatus = "streaming" | "loaded" | "error";
export type DownloadProgress = { bytes: number; total: number };

type StreamEvent = {
  log?: string;
  status?: string;
  detail?: string;
  progress?: DownloadProgress;
};

export function useModelDownloadStream(opts: { onLoaded?: () => void } = {}) {
  const [id, setId] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [status, setStatus] = useState<DownloadStatus>("streaming");
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<DownloadProgress | null>(null);
  const sseRef = useRef<AbortController | null>(null);
  const onLoadedRef = useRef(opts.onLoaded);
  useEffect(() => {
    onLoadedRef.current = opts.onLoaded;
  }, [opts.onLoaded]);

  const start = useCallback(async (modelId: string) => {
    setId(modelId);
    setLog([]);
    setStatus("streaming");
    setErr(null);
    setProgress(null);
    const ac = new AbortController();
    sseRef.current = ac;

    try {
      const res = await apiFetch(`/api/admin/models/${encodeURIComponent(modelId)}/status`, {
        signal: ac.signal,
      });
      if (!res.ok || !res.body) throw new Error(`status stream HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) !== -1) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          let evt: StreamEvent;
          try { evt = JSON.parse(line); } catch { continue; }
          if (evt.log) setLog(prev => [...prev, evt.log!]);
          if (evt.progress) setProgress(evt.progress);
          if (evt.status === "loaded") { setStatus("loaded"); onLoadedRef.current?.(); }
          if (evt.status === "error") { setStatus("error"); setErr(evt.detail || "unknown error"); }
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setStatus("error");
        setErr((e as Error).message);
      }
    }
  }, []);

  const cancel = useCallback(() => {
    sseRef.current?.abort();
    sseRef.current = null;
    setId(null);
  }, []);

  return { id, log, status, err, progress, start, cancel };
}
