"use client";

import { useEffect, useState } from "react";
import { APP_CONFIG } from "@/utils/constants";

/**
 * Engine tab — embeds llama-swap's UI via the /api/admin/engine/* reverse
 * proxy. Iframe is lazy-mounted (this whole route is, by virtue of being
 * its own Next.js page) and the iframe element only exists while we're
 * on this page.
 *
 * Known caveat: llama-swap's UI may emit absolute URLs (/assets/foo.js)
 * that break under the sub-path. If the iframe renders blank, check the
 * browser network tab — that's the failure mode to fix in v2.
 */
export default function AdminEnginePage() {
  // Trigger client-side mount before computing the URL — APP_CONFIG.API_URL
  // hits a getter that prefers the same-origin URL when available, and we
  // need the document context for that.
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSrc(`${APP_CONFIG.API_URL}/api/admin/engine/`);
  }, []);

  return (
    <div className="max-w-6xl">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold">Engine</h2>
        <p className="text-xs text-gray-500">
          Proxied through Pryzm&apos;s admin auth. llama-swap&apos;s own port
          (8080) is not exposed externally.
        </p>
      </div>

      <div className="border border-[#2a2a2c] rounded overflow-hidden bg-[#131314]">
        {src ? (
          <iframe
            src={src}
            title="llama-swap admin"
            className="w-full h-[calc(100vh-200px)] bg-white"
            // Cookie auth flows through naturally since the iframe URL
            // is same-origin to the rest of the app (or backend, depending
            // on the resolved API_URL).
          />
        ) : (
          <div className="h-[calc(100vh-200px)] flex items-center justify-center text-xs text-gray-500">
            Loading…
          </div>
        )}
      </div>
    </div>
  );
}
