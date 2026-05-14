# Upload UX Fixes — Design Spec

- **Date**: 2026-05-15
- **Status**: Draft, pending user approval.
- **Branch context**: spec authored on `main` at `d2eb99a`.
- **Trigger**: live mobile testing on Samsung Internet PWA surfaced four interacting issues.

## What's wrong today

1. **Gallery is missing from the mobile attach picker.** Tapping the photo button on Samsung Internet (Android, PWA) shows Camera + two file-manager apps, no Gallery. PR #36 split the attach button into Photo (`accept="image/*"`) and File (`accept=".txt,.md,..."`) precisely because mixed accept lists buried Gallery. The user has since flagged that two buttons is the wrong UX — one `+` button is correct, and the OS picker should surface Camera / Gallery / Files itself.
2. **The upload pill icon is generic.** Successful uploads land with a `DatabaseIcon`; the user wants the image's actual thumbnail.
3. **The in-flight indicator is a spinner, not progress.** The pill shows a slowly-rotating refresh-arrows icon. The user wants an **actual progress ring** that fills 0→100% during the byte transfer, like Claude/Gemini, so the wait state is legible.
4. **The desktop file picker hides supported files.** With strict-accept (the file button's `.txt,.md,.py,...` allowlist), GNOME/KDE/macOS dialogs filter aggressively; the user has to flip to "All files" to see anything. Reproduced on Linux desktop.
5. **`crypto.randomUUID is not a function` on mobile.** `utils/ids.ts` calls `crypto.randomUUID()` directly. That API requires a **secure context** (HTTPS or localhost). The PWA is loaded over `http://192.168.x.x:3000` (LAN, plain HTTP), so on Samsung Internet the call throws. Optimistic IDs aren't minted; sends fail before the network request leaves the device.

## Why mixed `accept` is the load-bearing root cause for #1 and #4

Per research ([AddPipe on Android 14/15 camera bug](https://blog.addpipe.com/html-file-input-accept-video-camera-option-is-missing-android-14-15/), [Android Photo Picker docs](https://developer.android.com/training/data-storage/shared/photo-picker), [how-to on multiple file options](https://www.w3tutorials.net/blog/multiple-file-options-when-upload-file-in-input-accept-attribute/)), Android Chrome and Samsung Internet both:

- show **Camera + Gallery + Files** when `accept="image/*"` exclusively
- often collapse Gallery into a generic "Files" entry when `accept` mixes MIMEs (e.g. `image/*,application/pdf`)
- on Samsung Internet specifically, revert to single-select or filter out non-matching files entirely when `accept` is a long extension list

Desktop pickers (GNOME, KDE, macOS) just filter by extension. With strict accept the user sees nothing; with `accept="*/*"` they see everything.

`accept="*/*"` is the only value that works consistently across Samsung Internet, Chrome on Android 14/15, GNOME, KDE, macOS, and Windows. The existing JS-side validation in `processFiles` (`validExts` check) already shows a clear error pill for unsupported types — so loose `accept` is safe.

## Architecture

Front-end-only changes. Backend is untouched.

```
ChatInput
  └── upload pill (per item in uploads[])
      ├── icon area  ← <CircularProgress value={u.progress}> overlay on thumbnail (in flight)
      │              ← <img blobUrl/> alone (success, image MIME)
      │              ← <DatabaseIcon> (success, other MIME)
      │              ← <AlertIcon> (error)
      └── filename + optional error message  (unchanged)

attach button (+)
  └── one hidden <input type=file accept=*/*>
      └── onChange → processFiles
          └── validExts filter        ← unchanged

useUploader
  └── per-item upload via XMLHttpRequest
      ├── upload.onprogress           ← drives u.progress 0..100
      ├── onload                      ← u.status='success'
      └── onerror / onabort           ← u.status='error'

utils/ids.ts
  └── safeRandomUUID()                ← wraps crypto.randomUUID(), Math.random fallback
```

## Components

### 1. `utils/ids.ts` — `safeRandomUUID` helper

- New private function `safeRandomUUID()` that returns `crypto.randomUUID()` when available, else a Math.random-derived v4-shaped UUID.
- Both `newOptimisticSessionId` and `newTempMessageId` switch to call it.
- Fallback is **not cryptographically secure**, but the IDs are short-lived UI temps that get replaced by the real DB UUID at stream start — collision risk on a single device is essentially zero. Documented in the comment.

### 2. `ChatInput.tsx` — single `+` attach button

- Drop the `ImageIcon` button and the `photoInputRef` added in PR #36. Keep the existing `PlusIcon` button.
- Set the surviving `<input type="file">`'s `accept` to `"*/*"`.
- `processFiles` already validates against `validExts` and tags unsupported files with `errorMessage: "Unsupported format"` — unchanged. Picker shows everything; JS gatekeeps post-pick.
- Remove the unused `ImageIcon` export from `Icons.tsx`.

### 3. `useUploader.ts` — switch to XHR for real progress

`fetch` doesn't expose upload progress events in a cross-browser way (Chrome 105+ supports `ReadableStream` upload bodies; Safari does not). The standard cross-browser path is `XMLHttpRequest` with `xhr.upload.addEventListener("progress", …)`.

Rewrite `processUploadQueue`'s per-item HTTP call as an XHR wrapped in a Promise:

```ts
function uploadWithProgress(file: File, form: FormData, onProgress: (pct: number) => void): Promise<Response> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${APP_CONFIG.API_URL}/upload`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    });
    xhr.onload = () => {
      // Adapt the XHR result to a fetch Response so caller code stays identical.
      resolve(new Response(xhr.responseText, { status: xhr.status }));
    };
    xhr.onerror = () => reject(new Error("Network error"));
    xhr.onabort = () => reject(new Error("Aborted"));
    xhr.send(form);
  });
}
```

`processUploadQueue` now calls this and threads the percentage into `setUploads`'s `progress` field. Once `e.loaded === e.total` the progress sits at 100; the pill UI then transitions to indeterminate (see component 4) until the XHR `onload` arrives — that's the gap where the backend is doing VLM captioning + embedding.

This deliberately doesn't introduce `apiFetch` for the upload — that wrapper is fetch-based. Keeping XHR scoped to this one call avoids a wider API surface change. Auth header injection is duplicated in-place; tradeoff is acceptable for one call site.

### 4. `components/CircularProgress.tsx` — new

Small SVG progress ring. One file, ~30 lines. Two states:

- **Determinate** (during XHR upload, `progress < 100`): a circle with `stroke-dasharray` set to the circumference, `stroke-dashoffset` tied to `(100 - progress)%`. Visually fills clockwise from 12 o'clock.
- **Indeterminate** (`progress === 100` but request hasn't resolved): the same ring with a shorter visible arc, rotated via `animate-spin` to indicate "still working." This is the post-bytes-sent / backend-processing window.

Sized to drop into the existing pill's 28×28 icon area. Stroke `currentColor` so it inherits the pill's text color (gray during upload, emerald on success state).

`LoadingIcon` is **not touched** — it stays the refresh-arrows shape for the chat-streaming indicator and other call sites. The new spinner is local to the upload pill.

### 5. `ChatInput.tsx` — pill renders the thumbnail and the ring

The pill currently renders:

```jsx
{u.status === "uploading" ? <LoadingIcon /> : <DatabaseIcon />}
<span>{u.file.name}</span>
```

New shape:

```jsx
<div className="relative w-7 h-7">
  {u.file.type.startsWith("image/") && u.previewUrl ? (
    <img src={u.previewUrl} className="w-7 h-7 object-cover rounded" alt="" />
  ) : (
    <DatabaseIcon className="w-7 h-7" />
  )}
  {u.status === "uploading" && (
    <CircularProgress
      value={u.progress}
      className="absolute inset-0"   // overlays the thumbnail
    />
  )}
  {u.status === "error" && <AlertIcon className="absolute inset-0" />}
</div>
<span>{u.file.name}</span>
```

`u.previewUrl` is `URL.createObjectURL(u.file)` computed once at the `processFiles` step where the upload first lands in state. On pill removal (`removeUpload`), on `clearQueue`, and on component unmount (`useEffect` cleanup), call `URL.revokeObjectURL` for every image-typed upload so blobs don't accumulate.

Thumbnail size 28×28 matches the existing pill height. `object-cover` crops without distortion.

**Re: do we resize the image?** No. The browser renders the blob URL at CSS size; no decode/re-encode needed. The full-size blob lives in memory only until the pill is removed.

### 6. `types/chat.ts` — `FileUpload` gains `previewUrl`

```ts
export interface FileUpload {
  ...existing fields...
  previewUrl?: string;   // set when file.type.startsWith("image/"); revoked on remove
}
```

`progress` is already on `FileUpload` per the current code — its semantics tighten from "0 / 50 / 100" to "0..100 real percentage from XHR progress events."

## Sequencing

Three small PRs, in this order. Each is independent (no shared file conflict):

| # | PR | Files touched | Risk |
|---|---|---|---|
| 1 | `crypto.randomUUID` polyfill | `frontend/src/utils/ids.ts` | None — additive helper |
| 2 | Single `+` button, `accept="*/*"` | `ChatInput.tsx`, `Icons.tsx` (remove `ImageIcon`) | Visible UX revert of PR #36 |
| 3 | Thumbnail + progress ring | `useUploader.ts`, `ChatInput.tsx`, `Icons.tsx`, `types/chat.ts`, `components/CircularProgress.tsx` (new) | Memory-leak risk if `revokeObjectURL` is missed → mitigated by `useEffect` cleanup |

The "Analyzing image…" caption PR that an earlier draft of this spec proposed has been **dropped**. It narrated the slowness without actually fixing it; the indeterminate ring state in PR 3 already conveys "still working" visually. Real async ingestion is the proper fix for upload latency and is explicitly deferred (see Out of scope).

## Out of scope

- **Async ingestion** (return `/upload` early, push progress via SSE). The right architecture is the WebSocket work in `docs/internal/2026-05-14-future-features.md` Item 4. PR 3's indeterminate-after-100% state is the visible bridge until that lands.
- **Client-side image resize before upload**. Considered and skipped — phone-camera photos haven't actually been painful enough yet.
- **Web Share Target API** ("share to Pryzm" from another Android app). Requires PWA manifest + service worker route; bigger lift than this set of fixes.
- **Replacing `LoadingIcon` everywhere**. The user has explicitly said the existing refresh-arrows spinner is fine for chat streaming and other call sites; only the upload pill gets the new progress ring.

## Testing

Frontend-only PRs and the repo has no JS test runner. Verification is manual:

- **Desktop check** (Linux/GNOME): open the dev frontend, click `+`, confirm the picker shows all files (not just supported extensions). Upload a small text file, confirm pill goes through ring → success. Upload a JPG, confirm thumbnail renders and ring fills as the bytes go up.
- **Mobile check** (Samsung Internet PWA on LAN): tap `+`, confirm Camera / Gallery / Files all appear; pick a photo, confirm thumbnail in the pill and the ring fills 0→100→indeterminate; confirm no `crypto.randomUUID` console error.
- **`pytest tests/`** — no regressions expected (frontend-only PRs), but run after each to confirm 168/168 unchanged.

## Karpathy alignment

- **Think before coding**: tradeoffs surfaced (XHR vs fetch+ReadableStream, global vs local spinner swap, real vs fake progress).
- **Simplicity first**: PR 4 dropped, `LoadingIcon` left alone, no client-side resize, no Web Share Target, no async ingestion.
- **Surgical changes**: each PR touches a tight file set. `CircularProgress` is one new file; the rest are local edits.
- **Goal-driven**: each PR has a concrete manual-verification step that proves the user-visible problem it fixes.

## Rollback

- PR 1: drop `safeRandomUUID`, restore bare `crypto.randomUUID()`. Mobile-on-LAN breaks again.
- PR 2: restore PR #36's two-button layout. Gallery vanishes again.
- PR 3: revert the thumbnail + ring. Pill returns to refresh-arrow + filename.
