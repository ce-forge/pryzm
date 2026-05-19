"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { HuggingFaceSearch } from "@/components/admin/system/HuggingFaceSearch";

type Model = {
  id: string;
  repo: string | null;
  quant: string | null;
  ngl: number | null;
  ctx_size: number | null;
  group: string | null;
  tags: string[];
  loaded: boolean;
};

const KNOWN_TAGS = ["embedding", "vision", "code"];

export default function ModelsSection() {
  const [models, setModels] = useState<Model[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [prefillId, setPrefillId] = useState("");
  const [prefillRepo, setPrefillRepo] = useState("");
  const [prefillFilename, setPrefillFilename] = useState<string | null>(null);
  const [prefillSize, setPrefillSize] = useState<number | null>(null);
  const [prefillBlobHash, setPrefillBlobHash] = useState<string | null>(null);
  const [downloadId, setDownloadId] = useState<string | null>(null);
  const [downloadLog, setDownloadLog] = useState<string[]>([]);
  const [downloadStatus, setDownloadStatus] = useState<"streaming" | "loaded" | "error">("streaming");
  const [downloadErr, setDownloadErr] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<{ bytes: number; total: number } | null>(null);
  const sseRef = useRef<AbortController | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/api/admin/models");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setModels(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initial + dep-change refresh of the models list. setState happens
  // inside `refresh`; the lint rule flags any call that ultimately
  // sets state from an effect, but this is the canonical "fetch on
  // mount and on dep change" pattern.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { refresh(); }, [refresh]);

  // Auto-scroll the log pane on every new line.
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [downloadLog]);

  const handleDelete = async (id: string) => {
    setConfirmDelete(null);
    try {
      const res = await apiFetch(`/api/admin/models/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleUpdate = async (id: string, patch: Partial<Model>) => {
    try {
      const res = await apiFetch(`/api/admin/models/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setEditingId(null);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const startDownloadStream = useCallback(async (id: string) => {
    setDownloadId(id);
    setDownloadLog([]);
    setDownloadStatus("streaming");
    setDownloadErr(null);
    setDownloadProgress(null);
    const ac = new AbortController();
    sseRef.current = ac;

    try {
      const res = await apiFetch(`/api/admin/models/${encodeURIComponent(id)}/status`, {
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
          let evt: {
            log?: string;
            status?: string;
            detail?: string;
            progress?: { bytes: number; total: number };
          };
          try { evt = JSON.parse(line); } catch { continue; }
          if (evt.log) setDownloadLog(prev => [...prev, evt.log!]);
          if (evt.progress) setDownloadProgress(evt.progress);
          if (evt.status === "loaded") { setDownloadStatus("loaded"); refresh(); }
          if (evt.status === "error") { setDownloadStatus("error"); setDownloadErr(evt.detail || "unknown error"); }
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setDownloadStatus("error");
        setDownloadErr((e as Error).message);
      }
    }
  }, [refresh]);

  const cancelDownload = () => {
    sseRef.current?.abort();
    sseRef.current = null;
    setDownloadId(null);
  };

  // Hard-cancel: abort the watcher AND delete the model entry so the
  // partial download stops on the llama-swap side. SIGHUP kills the
  // running llama-server process for that model id, which kills its
  // curl child — actual bytes stop flowing. Partial blob stays on disk
  // (the daily cleanup task reaps it).
  const abortDownload = async (id: string) => {
    const ok = window.confirm(
      `Cancel the download of "${id}"?\n\n` +
        `This removes the model entry from llama-swap. Any partial bytes ` +
        `stay cached on disk and resume if you re-add the same file later.`,
    );
    if (!ok) return;
    sseRef.current?.abort();
    sseRef.current = null;
    try {
      const res = await apiFetch(`/api/admin/models/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setDownloadId(null);
    refresh();
  };

  const handleAdded = (newId: string) => {
    setShowAddForm(false);
    refresh();
    startDownloadStream(newId);
  };

  return (
    <div className="border-t border-[#333537] pt-6">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-[#e3e3e3]">Models</h3>
        <button
          onClick={() => setShowAddForm(v => !v)}
          className="px-3 py-1 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          {showAddForm ? "Cancel" : "+ Add Model"}
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Models registered with llama-swap. Edits to <code className="font-mono text-xs bg-[#131314] px-1 py-0.5 rounded">infra/llama-swap-config.yaml</code> on disk also show up here.
      </p>

      {error && (
        <div className="mb-3 px-3 py-2 rounded-lg text-xs bg-red-900/30 border border-red-900 text-red-300">{error}</div>
      )}

      {showAddForm && (
        <>
          <HuggingFaceSearch
            onPick={({ id, repo, expected_filename, expected_size, expected_blob_hash }) => {
              setPrefillId(id);
              setPrefillRepo(repo);
              setPrefillFilename(expected_filename);
              setPrefillSize(expected_size);
              setPrefillBlobHash(expected_blob_hash);
            }}
          />
          <AddModelForm
            key={`${prefillId}:${prefillRepo}`}
            initialId={prefillId}
            initialRepo={prefillRepo}
            expectedFilename={prefillFilename}
            expectedSize={prefillSize}
            expectedBlobHash={prefillBlobHash}
            onAdded={handleAdded}
            onError={setError}
          />
        </>
      )}

      {downloadId && (
        <DownloadLogPane
          id={downloadId}
          log={downloadLog}
          status={downloadStatus}
          error={downloadErr}
          progress={downloadProgress}
          onClose={cancelDownload}
          onCancel={() => abortDownload(downloadId)}
          logEndRef={logEndRef}
        />
      )}

      <div className="space-y-2">
        {isLoading && models.length === 0 && (
          <div className="text-xs text-gray-500">Loading…</div>
        )}
        {models.map(m => (
          editingId === m.id ? (
            <EditModelRow
              key={m.id}
              model={m}
              onSave={(patch) => handleUpdate(m.id, patch)}
              onCancel={() => setEditingId(null)}
            />
          ) : (
            <div key={m.id} className="bg-[#131314] border border-[#333537] rounded-lg px-3 py-2 flex items-center justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-[#e3e3e3] truncate">{m.id}</span>
                  {m.group && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider ${m.group === "always-on" ? "bg-purple-900/40 text-purple-300" : "bg-blue-900/40 text-blue-300"}`}>
                      {m.group}
                    </span>
                  )}
                  {m.tags.map(t => (
                    <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-[#282a2c] text-gray-400">{t}</span>
                  ))}
                </div>
                {m.repo && (
                  <div className="text-[11px] text-gray-500 truncate font-mono">
                    {m.repo}{m.quant ? `:${m.quant}` : ""}
                    {(m.ngl !== null || m.ctx_size !== null) && (
                      <span className="text-gray-600"> · ngl={m.ngl ?? "—"} ctx={m.ctx_size ?? "—"}</span>
                    )}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-xs ${m.loaded ? "text-emerald-400" : "text-gray-500"}`} title={m.loaded ? "Loaded in VRAM" : "Not in VRAM — will load on first request"}>
                  {m.loaded ? "● loaded" : "○ unloaded"}
                </span>
                <button
                  onClick={() => setEditingId(m.id)}
                  className="px-2 py-1 rounded text-xs text-gray-500 hover:text-blue-400 transition-colors"
                  title="Edit GPU layers, context size, group, tags"
                >
                  Edit
                </button>
                {!m.tags.includes("embedding") && (
                  confirmDelete === m.id ? (
                    <>
                      <button onClick={() => handleDelete(m.id)} className="px-2 py-1 rounded text-xs bg-red-700 hover:bg-red-600 text-white">Confirm</button>
                      <button onClick={() => setConfirmDelete(null)} className="px-2 py-1 rounded text-xs text-gray-400 hover:text-white">Cancel</button>
                    </>
                  ) : (
                    <button
                      onClick={() => setConfirmDelete(m.id)}
                      className="px-2 py-1 rounded text-xs text-gray-500 hover:text-red-400 transition-colors"
                      title="Remove from llama-swap config (cached GGUF stays on disk)"
                    >
                      Delete
                    </button>
                  )
                )}
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  );
}

/**
 * Detect which load phase llama-server is in by scanning the tail of the log.
 * Returns a short human-readable label. llama-server's HF downloader in the
 * current build is silent (no percentage lines), so we use phase markers as
 * the user-visible signal instead.
 */
function detectPhase(log: string[]): string {
  // Walk newest → oldest looking for the latest phase marker we recognise.
  for (let i = log.length - 1; i >= 0 && i >= log.length - 200; i--) {
    const line = log[i];
    if (/server is listening|model loaded|Health check passed/i.test(line))
      return "Finalizing";
    if (/warming up the model|common_init_from_params/.test(line))
      return "Warming up";
    if (/llama_kv_cache|sched_reserve|llama_context: constructing/.test(line))
      return "Initializing context";
    if (/load_tensors:|llama_model_loader:|print_info:/.test(line))
      return "Loading tensors";
    if (/main: loading model|loading model from/.test(line))
      return "Reading model file";
    if (/common_download_file|downloading from|get_hf_plan/i.test(line))
      return "Fetching from HuggingFace";
  }
  return "Preparing";
}

/**
 * Tick a seconds counter while `active` is true. Freezes (doesn't reset) when
 * active flips to false, so the final elapsed time persists if the caller
 * wants to render it after completion.
 */
function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  const startRef = useRef<number | null>(null);
  useEffect(() => {
    if (!active) return;
    if (startRef.current === null) startRef.current = Date.now();
    const t = setInterval(() => {
      if (startRef.current !== null) {
        setSeconds(Math.floor((Date.now() - startRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(t);
  }, [active]);
  return seconds;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatEta(secondsRemaining: number): string {
  if (!isFinite(secondsRemaining) || secondsRemaining < 0) return "—";
  if (secondsRemaining < 60) return `~${Math.ceil(secondsRemaining)}s left`;
  const m = Math.floor(secondsRemaining / 60);
  const s = Math.ceil(secondsRemaining % 60);
  return `~${m}m ${s}s left`;
}

/**
 * Compute ETA in seconds based on observed download speed.
 * Anchors at the first non-zero progress event so the initial latency
 * (waiting for the download to start) doesn't poison the speed estimate.
 * Returns null until we have at least 2 seconds and 1 MiB of samples — early
 * speed numbers are noisy and would give wildly wrong ETAs.
 */
function useDownloadEta(
  progress: { bytes: number; total: number } | null,
): number | null {
  const [anchor, setAnchor] = useState<{ time: number; bytes: number } | null>(null);
  const [eta, setEta] = useState<number | null>(null);

  useEffect(() => {
    if (!progress || progress.total === 0 || progress.bytes >= progress.total) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (anchor !== null) setAnchor(null);
       
      if (eta !== null) setEta(null);
      return;
    }
    if (anchor === null && progress.bytes > 0) {
       
      setAnchor({ time: Date.now(), bytes: progress.bytes });
      return;
    }
    if (anchor === null) return;
    const elapsedSec = (Date.now() - anchor.time) / 1000;
    const bytesSince = progress.bytes - anchor.bytes;
    if (elapsedSec < 2 || bytesSince < 1024 * 1024) return;
    const speedBps = bytesSince / elapsedSec;
    if (speedBps <= 0) return;
     
    setEta((progress.total - progress.bytes) / speedBps);
  }, [progress, anchor, eta]);

  return eta;
}

function DownloadLogPane({
  id, log, status, error, progress, onClose, onCancel, logEndRef,
}: {
  id: string;
  log: string[];
  status: "streaming" | "loaded" | "error";
  error: string | null;
  progress: { bytes: number; total: number } | null;
  onClose: () => void;
  onCancel: () => void;
  logEndRef: React.RefObject<HTMLDivElement | null>;
}) {
  const phase = status === "streaming" ? detectPhase(log) : null;
  const elapsed = useElapsed(status === "streaming");
  const hasRealProgress = progress !== null && progress.total > 0 && progress.bytes < progress.total;
  const pct = hasRealProgress ? Math.min(100, (progress!.bytes / progress!.total) * 100) : 0;
  const etaSec = useDownloadEta(status === "streaming" ? progress : null);
  // Local collapse: the log scroller hides but the header + progress bar
  // stay visible so the admin can still see "Cancel" + ETA. Default to
  // collapsed — the logs are llama-server stderr noise most of the time
  // and the progress bar is the useful signal. Click Show to expand.
  const [collapsed, setCollapsed] = useState(true);
  return (
    <div className="mb-3 bg-[#0e0e0f] border border-[#333537] rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-[#131314] border-b border-[#333537]">
        <div className="text-xs text-gray-300">
          {status === "streaming" && <>Loading <span className="font-mono text-emerald-400">{id}</span>…</>}
          {status === "loaded" && <>Loaded <span className="font-mono text-emerald-400">{id}</span> ✓</>}
          {status === "error" && <>Error loading <span className="font-mono text-red-400">{id}</span>: {error}</>}
        </div>
        <div className="flex items-center gap-2">
          {status === "streaming" && (
            <button
              onClick={onCancel}
              className="text-xs px-2 py-0.5 rounded border border-red-500/30 text-red-300 hover:bg-red-500/15"
            >
              Cancel download
            </button>
          )}
          {status === "streaming" ? (
            <button
              onClick={() => setCollapsed((c) => !c)}
              className="text-xs text-gray-500 hover:text-white"
            >
              {collapsed ? "Show logs" : "Hide logs"}
            </button>
          ) : (
            <button onClick={onClose} className="text-xs text-gray-500 hover:text-white">
              Close
            </button>
          )}
        </div>
      </div>
      {status === "streaming" && (
        <div className="px-3 py-2 bg-[#131314] border-b border-[#333537]">
          <div className="flex items-center justify-between mb-1.5 text-[11px]">
            <span className="text-gray-300">
              {phase}…
              {hasRealProgress && (
                <span className="text-gray-500 font-mono ml-2">
                  {formatBytes(progress!.bytes)} / {formatBytes(progress!.total)} ({pct.toFixed(1)}%)
                </span>
              )}
            </span>
            <span className="text-gray-500 font-mono">
              {etaSec !== null ? formatEta(etaSec) : formatElapsed(elapsed)}
            </span>
          </div>
          <div className="h-2 rounded bg-[#2a2a2c] overflow-hidden">
            {hasRealProgress ? (
              <div
                className="h-full bg-blue-500 transition-[width] duration-500 ease-out"
                style={{ width: `${pct}%` }}
              />
            ) : (
              <div className="indeterminate-bar h-full bg-blue-500" />
            )}
          </div>
          {!hasRealProgress && phase === "Fetching from HuggingFace" && (
            <p className="text-[10px] text-gray-500 mt-1.5 leading-relaxed">
              Waiting for the download to start writing to the cache. Multi-GB
              GGUFs can take a few minutes — once bytes start flowing, real
              progress will replace this spinner.
            </p>
          )}
        </div>
      )}
      {!collapsed && (
        <div className="px-3 py-2 max-h-48 overflow-y-auto custom-scrollbar font-mono text-[11px] leading-5 text-gray-400">
          {log.length === 0 && status === "streaming" && (
            <div className="text-gray-600">Waiting for llama-swap output…</div>
          )}
          {log.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">{line}</div>
          ))}
          <div ref={logEndRef} />
        </div>
      )}
    </div>
  );
}

function AddModelForm({
  initialId = "",
  initialRepo = "",
  expectedFilename = null,
  expectedSize = null,
  expectedBlobHash = null,
  onAdded,
  onError,
}: {
  initialId?: string;
  initialRepo?: string;
  expectedFilename?: string | null;
  expectedSize?: number | null;
  expectedBlobHash?: string | null;
  onAdded: (id: string) => void;
  onError: (msg: string) => void;
}) {
  const [id, setId] = useState(initialId);
  const [repo, setRepo] = useState(initialRepo);
  const [ngl, setNgl] = useState(99);
  const [ctxSize, setCtxSize] = useState(8192);
  const [group, setGroup] = useState<"chat" | "always-on" | "inactive">("chat");
  const [tags, setTags] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!id.trim() || !repo.trim()) return;
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/admin/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: id.trim(),
          repo: repo.trim(),
          ngl,
          ctx_size: ctxSize,
          group,
          tags,
          expected_filename: expectedFilename,
          expected_size: expectedSize,
          expected_blob_hash: expectedBlobHash,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const created = await res.json();
      onAdded(created.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleTag = (t: string) => setTags(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);

  return (
    <div className="mb-3 bg-[#131314] border border-[#333537] rounded-lg p-3 space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Name (id)" hint="letters, digits, dash, dot, underscore">
          <input
            value={id}
            onChange={e => setId(e.target.value)}
            placeholder="e.g. qwen-coder-7b"
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
          />
        </Field>
        <Field label="HuggingFace repo:quant" hint="org/repo:Quant">
          <input
            value={repo}
            onChange={e => setRepo(e.target.value)}
            placeholder="bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M"
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500 font-mono"
          />
        </Field>
        <Field label="GPU layers (ngl)">
          <input
            type="number" value={ngl} onChange={e => setNgl(parseInt(e.target.value) || 0)}
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
          />
        </Field>
        <Field label="Context size">
          <input
            type="number" value={ctxSize} onChange={e => setCtxSize(parseInt(e.target.value) || 0)}
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
          />
        </Field>
        <Field label="Group">
          <select
            value={group} onChange={e => setGroup(e.target.value as "chat" | "always-on" | "inactive")}
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
          >
            <option value="chat">chat</option>
            <option value="always-on">always-on</option>
            <option value="inactive">inactive</option>
          </select>
        </Field>
        <Field label="Tags">
          <div className="flex flex-wrap gap-1.5 pt-1">
            {KNOWN_TAGS.map(t => (
              <button
                key={t}
                type="button"
                onClick={() => toggleTag(t)}
                className={`px-2 py-0.5 rounded text-xs border transition-colors ${tags.includes(t) ? "bg-blue-900/40 border-blue-700 text-blue-200" : "bg-[#0e0e0f] border-[#333537] text-gray-500 hover:text-gray-300"}`}
              >
                {t}
              </button>
            ))}
          </div>
        </Field>
      </div>
      <div className="flex justify-end">
        <button
          onClick={submit}
          disabled={submitting || !id.trim() || !repo.trim()}
          className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:bg-[#282a2c] disabled:text-gray-500 disabled:cursor-not-allowed"
        >
          {submitting ? "Adding…" : "Add and download"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-mono text-gray-400 uppercase tracking-wider">{label}</span>
      {children}
      {hint && <span className="text-[10px] text-gray-600">{hint}</span>}
    </label>
  );
}

function EditModelRow({
  model, onSave, onCancel,
}: {
  model: Model;
  onSave: (patch: { ngl?: number; ctx_size?: number; group?: string; tags?: string[] }) => void;
  onCancel: () => void;
}) {
  // Identity fields (id, repo, quant) are shown read-only — to change those,
  // the user deletes + re-adds.
  const [ngl, setNgl] = useState(model.ngl ?? 99);
  const [ctxSize, setCtxSize] = useState(model.ctx_size ?? 8192);
  const [group, setGroup] = useState<"chat" | "always-on" | "inactive">(
    (["always-on", "inactive"].includes(model.group ?? "")
      ? (model.group as "always-on" | "inactive")
      : "chat"),
  );
  const [tags, setTags] = useState<string[]>(model.tags);

  const toggleTag = (t: string) => setTags(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);

  return (
    <div className="bg-[#0e0e0f] border border-blue-900 rounded-lg p-3 space-y-3">
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm text-[#e3e3e3]">{model.id}</span>
        <span className="text-[11px] text-gray-500 font-mono truncate">
          {model.repo}{model.quant ? `:${model.quant}` : ""}
        </span>
        <span className="text-[10px] text-gray-600">(repo:quant not editable — delete + re-add to change)</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="GPU layers (ngl)">
          <input
            type="number" value={ngl} onChange={e => setNgl(parseInt(e.target.value) || 0)}
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
          />
        </Field>
        <Field label="Context size">
          <input
            type="number" value={ctxSize} onChange={e => setCtxSize(parseInt(e.target.value) || 0)}
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
          />
        </Field>
        <Field label="Group">
          <select
            value={group} onChange={e => setGroup(e.target.value as "chat" | "always-on" | "inactive")}
            className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
          >
            <option value="chat">chat</option>
            <option value="always-on">always-on</option>
            <option value="inactive">inactive</option>
          </select>
        </Field>
        <Field label="Tags">
          <div className="flex flex-wrap gap-1.5 pt-1">
            {KNOWN_TAGS.map(t => (
              <button
                key={t}
                type="button"
                onClick={() => toggleTag(t)}
                className={`px-2 py-0.5 rounded text-xs border transition-colors ${tags.includes(t) ? "bg-blue-900/40 border-blue-700 text-blue-200" : "bg-[#0e0e0f] border-[#333537] text-gray-500 hover:text-gray-300"}`}
              >
                {t}
              </button>
            ))}
          </div>
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white">Cancel</button>
        <button
          onClick={() => onSave({ ngl, ctx_size: ctxSize, group, tags })}
          className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white"
        >
          Save
        </button>
      </div>
    </div>
  );
}
