"use client";
/**
 * Inline image previews for documents the auto-RAG path retrieved.
 *
 * Rendered below an assistant turn's prose when the backend emitted a
 * `files_referenced` SSE event during the chat stream. v1: image MIMEs
 * only — non-image referenced docs (PDFs, text) get no preview because
 * we don't persist their original bytes for inline rendering.
 *
 * Each image fetches from `GET /documents/{id}/raw` with the bearer
 * token in the URL (browser <img> can't set custom headers). The
 * backend marks the response cache-immutable so subsequent renders /
 * page reloads hit the browser cache.
 */
import type { ReferencedFile } from "@/types/chat";
import { APP_CONFIG } from "@/utils/constants";
import { getToken } from "@/utils/apiClient";


export default function ReferencedFilesPreview({ files }: { files: ReferencedFile[] }) {
  const images = files.filter((f) => f.mime.startsWith("image/"));
  if (images.length === 0) return null;

  const token = getToken();

  return (
    <div className="mt-2 flex flex-col gap-2 w-full max-w-2xl">
      {images.map((f) => {
        const params = token ? `?token=${encodeURIComponent(token)}` : "";
        const url = `${APP_CONFIG.API_URL}/documents/${f.id}/raw${params}`;
        return (
          <a
            key={f.id}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="block rounded-xl overflow-hidden border border-[#333537] bg-[#1e1f20] hover:border-[#4f5152] transition-colors"
            title={f.filename}
          >
            {/* Plain <img> — browser handles caching by URL, native
                zoom on pinch/double-tap on mobile, and the surrounding
                <a target="_blank"> opens the full image for power
                zoom. eslint-disabled because data-streaming images
                aren't well-served by next/image (would require a
                custom loader for our auth-bearing URLs). */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={url}
              alt={f.filename}
              className="block w-full h-auto max-h-[420px] object-contain"
              loading="lazy"
            />
            <div className="px-3 py-1.5 text-[11px] text-gray-400 truncate">
              {f.filename}
            </div>
          </a>
        );
      })}
    </div>
  );
}
