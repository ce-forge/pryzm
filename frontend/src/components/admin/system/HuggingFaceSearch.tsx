"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

interface HfRepo {
  id: string;
  downloads: number;
  likes: number;
  tags: string[];
  last_modified: string | null;
}

interface HfFile {
  path: string;
  size: number;
}

/**
 * Slugify an HF repo id into a friendly model id.
 * `bartowski/Qwen2.5-Coder-7B-Instruct-GGUF` → `qwen2.5-coder-7b-instruct`.
 * Strips the trailing `-GGUF` / `-gguf` suffix that nearly every repo has.
 */
function slugFromRepo(repoId: string): string {
  const tail = repoId.includes("/") ? repoId.split("/").slice(-1)[0] : repoId;
  return tail
    .replace(/-gguf$/i, "")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .toLowerCase();
}

function formatBytes(bytes: number): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function HuggingFaceSearch({
  onPick,
}: {
  onPick: (picked: { id: string; repo: string }) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<HfRepo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRepo, setExpandedRepo] = useState<string | null>(null);
  const [files, setFiles] = useState<Record<string, HfFile[]>>({});
  const [filesLoading, setFilesLoading] = useState<string | null>(null);
  const [filesError, setFilesError] = useState<Record<string, string>>({});

  // Debounce the search query so each keystroke doesn't fire a request.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) {
      setResults([]);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    debounceRef.current = setTimeout(() => {
      apiFetch(`/api/admin/hf-search?q=${encodeURIComponent(q.trim())}&limit=20`)
        .then(async (r) => {
          if (!r.ok) {
            setError(`Search failed (${r.status})`);
            setResults([]);
            return;
          }
          setError(null);
          const body = await r.json();
          setResults(Array.isArray(body) ? body : []);
        })
        .catch((e) => {
          setError(String(e));
          setResults([]);
        })
        .finally(() => setLoading(false));
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [q]);

  const toggleExpand = async (repoId: string) => {
    if (expandedRepo === repoId) {
      setExpandedRepo(null);
      return;
    }
    setExpandedRepo(repoId);
    if (files[repoId]) return;
    setFilesLoading(repoId);
    try {
      const r = await apiFetch(
        `/api/admin/hf-files?repo=${encodeURIComponent(repoId)}`,
      );
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setFilesError((prev) => ({
          ...prev,
          [repoId]: body.detail || `Failed (${r.status})`,
        }));
        return;
      }
      const body = await r.json();
      setFiles((prev) => ({ ...prev, [repoId]: Array.isArray(body) ? body : [] }));
    } catch (e) {
      setFilesError((prev) => ({ ...prev, [repoId]: String(e) }));
    } finally {
      setFilesLoading(null);
    }
  };

  const pickFile = (repoId: string, filePath: string) => {
    onPick({
      id: slugFromRepo(repoId),
      repo: `${repoId}:${filePath}`,
    });
  };

  return (
    <div className="mb-3 bg-[#131314] border border-[#333537] rounded-lg p-3 space-y-3">
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-mono text-gray-400 uppercase tracking-wider">
          Search HuggingFace
        </span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. qwen 3 coder, llama 3.1 instruct"
          className="w-full bg-[#0e0e0f] border border-[#333537] text-sm rounded-lg px-2 py-1.5 outline-none focus:border-blue-500"
        />
      </label>

      {error && <div className="text-xs text-red-400">{error}</div>}

      {loading && (
        <div className="text-xs text-gray-500 italic">Searching…</div>
      )}

      {!loading && q.trim() && results.length === 0 && !error && (
        <div className="text-xs text-gray-500 italic">No matches.</div>
      )}

      {results.length > 0 && (
        <ul className="space-y-1.5 max-h-96 overflow-y-auto custom-scrollbar">
          {results.map((repo) => {
            const isExpanded = expandedRepo === repo.id;
            const repoFiles = files[repo.id];
            const repoError = filesError[repo.id];
            const isLoadingFiles = filesLoading === repo.id;
            return (
              <li
                key={repo.id}
                className="border border-[#333537] rounded bg-[#0e0e0f]"
              >
                <button
                  type="button"
                  onClick={() => toggleExpand(repo.id)}
                  className="w-full flex items-start justify-between gap-3 p-2 text-left hover:bg-[#1a1a1b]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-sm text-[#e3e3e3] truncate">
                      {repo.id}
                    </div>
                    <div className="text-xs text-gray-500 flex flex-wrap gap-2 mt-0.5">
                      <span>↓ {formatCount(repo.downloads)}</span>
                      <span>♥ {formatCount(repo.likes)}</span>
                      {repo.tags.includes("text-generation") && (
                        <span className="text-blue-300">chat</span>
                      )}
                      {repo.tags.includes("feature-extraction") && (
                        <span className="text-emerald-300">embedding</span>
                      )}
                      {repo.tags.includes("image-text-to-text") && (
                        <span className="text-amber-300">vision</span>
                      )}
                    </div>
                  </div>
                  <span className="text-xs text-gray-500 mt-0.5">
                    {isExpanded ? "▾" : "▸"}
                  </span>
                </button>

                {isExpanded && (
                  <div className="border-t border-[#333537] p-2 space-y-1">
                    {isLoadingFiles && (
                      <div className="text-xs text-gray-500 italic">
                        Loading files…
                      </div>
                    )}
                    {repoError && (
                      <div className="text-xs text-red-400">{repoError}</div>
                    )}
                    {repoFiles && repoFiles.length === 0 && (
                      <div className="text-xs text-gray-500 italic">
                        No GGUF files in this repo.
                      </div>
                    )}
                    {repoFiles && repoFiles.length > 0 && (
                      <ul className="space-y-0.5">
                        {repoFiles.map((f) => (
                          <li key={f.path}>
                            <button
                              type="button"
                              onClick={() => pickFile(repo.id, f.path)}
                              className="w-full flex items-center justify-between gap-3 px-2 py-1 rounded hover:bg-[#1a1a1b] text-left"
                            >
                              <span className="font-mono text-xs text-[#e3e3e3] truncate">
                                {f.path}
                              </span>
                              <span className="text-xs text-gray-500 shrink-0">
                                {formatBytes(f.size)}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
