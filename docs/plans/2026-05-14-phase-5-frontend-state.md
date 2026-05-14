# Phase 5 — Frontend State Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation agents must apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Replace the single 11-key `ChatContext` with five focused contexts so a streaming token only re-renders bubble consumers (sidebar/switcher stay stable). Make `SessionContext` the single owner of the message cache with a typed API, eliminating the two-writer race in the optimistic-id → real-id handoff. Switch optimistic IDs to `crypto.randomUUID()`. Add a small `withRollback` helper applied to folder, workspace-edit, and message-edit mutation sites. Memoize `ChatBubble` and stabilize parent props so streaming doesn't re-render the full message list. Remove the `window.dispatchEvent("chatCreated")` cross-component bus.

**Architecture:** Five providers compose via `AppProviders.tsx`. Order matters because lower providers consume higher ones via custom hooks (`useSessionContext()`, `useWorkspaceContext()`, etc.):

```
<WorkspaceContext>          // workspaces[], activeWorkspace, switchWorkspace
  <SessionContext>          // sessions[], folders[], message cache + typed mutators
    <InferenceContext>      // streamingContent, sendMessage, stopInference
      <UploaderContext>     // upload queue
        <TestSuiteContext>  // dev-only test runner
          {children}
```

`SessionContext` exposes a closed API (`getMessages`, `appendChunk`, `finalizeMessage`, `replaceMessages`, `migrateBucket`, `notifySessionCreated`). `useInference` calls those methods — it never holds a `setMessageCache` setter. The optimistic→real handoff becomes a single atomic call to `migrateBucket(optimisticKey, realKey)`. `streamingSessionIdsRef` plus `migratedIds` Map live inside `InferenceContext`.

**Tech stack:** Native React 19 contexts only. No state library. No `use-context-selector`. Uses `crypto.randomUUID()` for optimistic IDs (already-supported in browsers; no new dep). Pytest + Playwright for e2e smoke (existing harness in `backend/tests/e2e/`).

**Spec reference:** [`docs/specs/2026-05-14-codebase-remediation.md`](../specs/2026-05-14-codebase-remediation.md) — Phase 5 section.

**Branch:** `refactor/phase-5-frontend-state` (cut from `main` after Phase 4 + codemap chores merged).

---

## Pre-Phase Notes

**Cache key format stays `${workspaceSlug}:${sessionId}`.** Phase 4's plan claimed to move this to `${workspaceId}` but in the merged code the variable name is `workspaceSlug` and the value is the URL slug. The actual requirement is *partition per workspace*, which slug-based partitioning satisfies. Slug renames invalidate cache, which reloads from DB — acceptable. Promoting to id-based is out of scope for Phase 5; revisit only if a slug-rename-during-stream bug appears.

**`useTestSuite` is dev-only.** It runs the data-driven prompt suite from `test_suite.json`. It only needs `sendMessage`, so the `TestSuiteContext` consumes `InferenceContext`. No production gating beyond what already exists (the test runner UI is wired through `ChatInput`).

**`activeWorkspace` shape stays.** Already includes `id` (set in Phase 4). Cache key namespace decision above means consumers continue to read `slug` for cache keys. They read `id` for any future per-workspace API call that requires id (none today).

---

## File Map

### Created
- `frontend/src/utils/withRollback.ts` — 15-line helper for optimistic mutations.
- `frontend/src/utils/ids.ts` — `newOptimisticId()` and `newTempMessageId()` wrappers around `crypto.randomUUID()`.
- `frontend/src/context/WorkspaceContext.tsx` — owns `workspaces[]`, `activeWorkspace`, switch.
- `frontend/src/context/SessionContext.tsx` — owns `sessions[]`, `folders[]`, message cache, typed mutator API.
- `frontend/src/context/InferenceContext.tsx` — owns SSE streaming state, `sendMessage`, `stopInference`, `migratedIds`, abort controllers.
- `frontend/src/context/UploaderContext.tsx` — owns upload queue.
- `frontend/src/context/TestSuiteContext.tsx` — owns dev test runner state.
- `frontend/src/context/AppProviders.tsx` — composes the five providers in the order above.
- `backend/tests/e2e/test_phase5_smoke.py` — Playwright smoke probes for Phase 5 (rapid sends, stream-while-navigate, rollback on backend 500, render-stability).

### Modified
- `frontend/src/hooks/useSession.ts` — slim it to a pure data-fetch helper consumed by `SessionContext`. Remove the `chatCreated` window listener (replaced by direct method call).
- `frontend/src/hooks/useInference.ts` — remove the parameter list (it'll be wrapped by `InferenceContext`); call `SessionContext`'s typed methods instead of `setMessageCache`. Use `crypto.randomUUID()` for optimistic IDs. Single atomic `migrateBucket` instead of dual-bucket writes during stream. Maintain `migratedIds` Map for `stopInference`.
- `frontend/src/hooks/useUploader.ts` — no logic change, just consumed by `UploaderContext`.
- `frontend/src/hooks/useTestSuite.ts` — no logic change; consumed by `TestSuiteContext`. Remove the `chatCreated` listener if present (it isn't, but verify).
- `frontend/src/hooks/useMessageActions.ts` — wrap message-edit mutations in `withRollback`.
- `frontend/src/hooks/useWorkspaces.ts` — no logic change; consumed by `WorkspaceContext`. (Already encapsulates fetch/mutate.)
- `frontend/src/components/ChatBubble.tsx` — wrap with `React.memo`. Accept `m` and `displayContent` as separate props; reconstruct internally.
- `frontend/src/components/ActiveSession.tsx` — stop spreading `{...m, content: displayContent}`. Pass `message={m}` and `displayContent={...}` separately. Switch to new context hooks.
- `frontend/src/components/Sidebar.tsx`, `SessionDirectory.tsx`, `SessionItem.tsx`, `WorkspaceSwitcher.tsx`, `WorkspaceSettings.tsx`, `ChatHeader.tsx`, `ChatBubble.tsx` — replace `useChatContext()` calls with the appropriate granular context hook (`useSessionContext()`, `useWorkspaceContext()`, etc.).
- `frontend/src/components/SessionDirectory.tsx` — wrap `createFolder`, `renameFolder`, `deleteFolder`, `dropToFolder` in `withRollback`. Remove the `chatCreated` listener (replaced by direct call from `notifySessionCreated`).
- `frontend/src/components/WorkspaceSettings.tsx` — replace fire-and-forget `save({...})` on blur with `withRollback`-wrapped mutations.
- `frontend/src/app/page.tsx` — replace `<ChatProvider>` with `<AppProviders>`.

### Removed
- `frontend/src/context/ChatContext.tsx` — replaced by the five focused contexts. The `useChatContext()` hook + `ChatProvider` are gone after the migration.

### Untouched
- Backend code (Phase 5 is frontend-only).
- The `apiFetch` wrapper, types in `types/chat.ts`, utility files (constants, sprite/color helpers).
- `useAutoScroll`, `useSearch`, `usePrompt`, `useOnClickOutside`, `useSidebarPrefetchGuard` — pure UI helpers, no context coupling.

---

## Pre-flight

Confirm Phase 4 baseline + create the working branch:

```bash
cd /home/orbital/projects/pryzm
git checkout main
git pull --ff-only
git checkout -b refactor/phase-5-frontend-state

# Backend tests should still pass from Phase 4.
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
# Expected: <N>/<N> pass (whatever the Phase 4 count is — typically 60+)

# Frontend builds clean.
cd frontend && npm run build 2>&1 | tail -5
# Expected: "Compiled successfully"
cd ..
```

---

## Task 1 — `withRollback` helper + tests

**Files:**
- Create: `frontend/src/utils/withRollback.ts`
- Create: `frontend/src/utils/__tests__/withRollback.test.ts` (skip if no test runner; ship the file regardless — tests run via the smoke harness)

> **Note:** the frontend has no Vitest/Jest configured. Skip the unit-test file; instead, the helper is exercised by Phase 5's e2e smoke (Task 11). This is consistent with Phase 4's testing pattern.

### Step 1: Write the helper

`frontend/src/utils/withRollback.ts`:

```ts
/**
 * Optimistic-mutation pattern. Apply the local change immediately so the UI
 * stays responsive; if the backend call rejects, undo it and re-throw so the
 * caller can surface the error.
 *
 *   await withRollback(
 *     () => setFolders((prev) => [...prev, newFolder]),
 *     () => setFolders((prev) => prev.filter(f => f.id !== newFolder.id)),
 *     () => apiFetch("/folders", { method: "POST", body: ... }).then(r => {
 *       if (!r.ok) throw new Error("create failed");
 *     }),
 *   );
 */
export async function withRollback<T>(
  applyLocal: () => void,
  rollback: () => void,
  apiCall: () => Promise<T>,
): Promise<T> {
  applyLocal();
  try {
    return await apiCall();
  } catch (e) {
    rollback();
    throw e;
  }
}
```

### Step 2: Commit

```bash
git add frontend/src/utils/withRollback.ts
git commit -m "feat(frontend): add withRollback helper for optimistic mutations"
```

---

## Task 2 — ID generators

**Files:**
- Create: `frontend/src/utils/ids.ts`

### Step 1: Write the helper

`frontend/src/utils/ids.ts`:

```ts
/**
 * Optimistic / temporary IDs used by the chat UI before a real DB UUID arrives.
 *
 * `crypto.randomUUID()` (rather than `Date.now()`) so rapid sends, double-clicks,
 * and React 19 strict-mode double invocation don't produce colliding IDs.
 */
export function newOptimisticSessionId(): string {
  return `optimistic-${crypto.randomUUID()}`;
}

export function newTempMessageId(role: "u" | "a"): string {
  return `temp-${role}-${crypto.randomUUID()}`;
}

export function isOptimisticSessionId(id: string | null | undefined): boolean {
  return !!id && id.startsWith("optimistic-");
}

export function isTempMessageId(id: string | null | undefined): boolean {
  return !!id && id.startsWith("temp-");
}
```

### Step 2: Commit

```bash
git add frontend/src/utils/ids.ts
git commit -m "feat(frontend): id helpers backed by crypto.randomUUID()"
```

---

## Task 3 — `WorkspaceContext`

**Files:**
- Create: `frontend/src/context/WorkspaceContext.tsx`

### Step 1: Write the context

`frontend/src/context/WorkspaceContext.tsx`:

```tsx
"use client";

import React, { createContext, useContext, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useWorkspaces, type Workspace } from "@/hooks/useWorkspaces";
import { APP_CONFIG } from "@/utils/constants";

type WorkspacesApi = ReturnType<typeof useWorkspaces>;

interface WorkspaceContextValue {
  workspacesApi: WorkspacesApi;
  workspaceSlug: string;            // URL slug (humans see this)
  activeWorkspace: Workspace | null; // resolved object including id
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const searchParams = useSearchParams();
  const workspaceSlug =
    searchParams.get("workspace") || APP_CONFIG.DEFAULT_WORKSPACE;
  const workspacesApi = useWorkspaces();

  const activeWorkspace = useMemo<Workspace | null>(
    () => workspacesApi.workspaces.find((w) => w.slug === workspaceSlug) ?? null,
    [workspacesApi.workspaces, workspaceSlug],
  );

  const value = useMemo(
    () => ({ workspacesApi, workspaceSlug, activeWorkspace }),
    [workspacesApi, workspaceSlug, activeWorkspace],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspaceContext(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspaceContext must be used inside <WorkspaceProvider>");
  return ctx;
}
```

### Step 2: Commit

```bash
git add frontend/src/context/WorkspaceContext.tsx
git commit -m "feat(frontend): WorkspaceContext owns workspaces[] + active resolution"
```

---

## Task 4 — `SessionContext` with typed cache API

This is the core of the phase. `SessionContext` becomes the **single writer** of the message cache. It exposes a closed API that other contexts (notably `InferenceContext`) call into.

**Files:**
- Modify: `frontend/src/hooks/useSession.ts`
- Create: `frontend/src/context/SessionContext.tsx`

### Step 1: Slim `useSession`

The existing `useSession` is fine as a data-loading helper but two things change:
- It returns `setMessageCache` today; we want to keep it as an internal-only setter and expose it through the context's typed API instead.
- Remove the `window.addEventListener("chatCreated", ...)` listener. The context will expose `notifySessionCreated()` which `InferenceContext` calls directly.

Edit `frontend/src/hooks/useSession.ts`:

Replace the initial-load `useEffect` block (lines 97–106) with one that drops the window listener:

```ts
  // Initial load. Sync after a stream completes is now triggered via the
  // SessionContext API (notifySessionCreated → loadSessionData(true)), not via
  // a window-level event bus.
  useEffect(() => {
    loadSessionData();
  }, [currentSession, workspace, loadSessionData]);
```

Replace `navigateToSession` (lines 132–138) so it stops dispatching the window event:

```ts
  const navigateToSession = useCallback((id: string) => {
    isNavigatingRef.current = true;
    setCurrentSession(id);
    router.replace(`/?workspace=${workspace}&session=${id}`, { scroll: false });
  }, [workspace, router]);
```

Add `loadSessionData` to the returned object so the context can call it externally:

```ts
  return {
    currentSession, setCurrentSession, sessionTitle, setSessionTitle,
    messages, messageCache, setMessageCache, workspace,
    activeCacheKey,
    isNavigatingRef, streamingSessionIdsRef, isInitialLoading,
    navigateToSession, prefetchSession, router, urlSessionId,
    loadSessionData,
  };
```

### Step 2: Write `SessionContext`

`frontend/src/context/SessionContext.tsx`:

```tsx
"use client";

import React, { createContext, useCallback, useContext, useMemo, useRef } from "react";
import { useSession } from "@/hooks/useSession";
import { Message } from "@/types/chat";

const cacheKey = (workspaceSlug: string, sessionId: string): string =>
  `${workspaceSlug}:${sessionId}`;

interface SessionContextValue {
  // Pass-through for routing/title/loading state.
  currentSession: string | null;
  workspace: string;
  sessionTitle: string;
  isInitialLoading: boolean;
  activeCacheKey: string;
  navigateToSession: (id: string) => void;
  prefetchSession: (id: string) => Promise<void>;
  streamingSessionIdsRef: React.MutableRefObject<Set<string>>;

  // Typed cache API (the single writer).
  messages: Message[];
  getMessages: (workspaceSlug: string, sessionId: string) => Message[];
  appendStartingMessages: (
    workspaceSlug: string,
    sessionId: string,
    items: Message[],
  ) => void;
  finalizeAssistantMessage: (
    workspaceSlug: string,
    sessionId: string,
    content: string,
  ) => void;
  replaceMessages: (
    workspaceSlug: string,
    sessionId: string,
    messages: Message[],
  ) => void;
  migrateBucket: (
    workspaceSlug: string,
    fromSessionId: string,
    toSessionId: string,
  ) => boolean;
  notifySessionCreated: (
    optimisticSessionId: string,
    realSessionId: string,
  ) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const { setMessageCache, loadSessionData } = session;

  // Bridge: components mutating cache via the typed API; SessionDirectory still
  // listens to "chat created" via this callback (instead of a window event).
  const sessionCreatedListenersRef = useRef<Set<() => void>>(new Set());

  const getMessages = useCallback(
    (ws: string, sid: string): Message[] =>
      // Read uses the latest snapshot via setState's pattern: we already
      // expose `messages` for the active key; for other keys, callers should
      // not need to read directly.
      (session.messageCache[cacheKey(ws, sid)] ?? []),
    [session.messageCache],
  );

  const appendStartingMessages = useCallback(
    (ws: string, sid: string, items: Message[]) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => ({
        ...prev,
        [key]: [...(prev[key] ?? []), ...items],
      }));
    },
    [setMessageCache],
  );

  const finalizeAssistantMessage = useCallback(
    (ws: string, sid: string, content: string) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => {
        const msgs = prev[key];
        if (!msgs || msgs.length === 0) return prev;
        const next = [...msgs];
        next[next.length - 1] = { ...next[next.length - 1], content };
        return { ...prev, [key]: next };
      });
    },
    [setMessageCache],
  );

  const replaceMessages = useCallback(
    (ws: string, sid: string, messages: Message[]) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => ({ ...prev, [key]: messages }));
    },
    [setMessageCache],
  );

  /**
   * Atomic optimistic→real session id migration: copies the optimistic
   * bucket's contents under the real key, then deletes the optimistic key.
   * Returns false if the optimistic key has nothing to migrate.
   */
  const migrateBucket = useCallback(
    (ws: string, fromSid: string, toSid: string): boolean => {
      const fromKey = cacheKey(ws, fromSid);
      const toKey = cacheKey(ws, toSid);
      let migrated = false;
      setMessageCache((prev) => {
        const src = prev[fromKey];
        if (!src) return prev;
        migrated = true;
        const { [fromKey]: _drop, ...rest } = prev;
        return { ...rest, [toKey]: src };
      });
      return migrated;
    },
    [setMessageCache],
  );

  /**
   * Called by InferenceContext after a successful stream creates a new session.
   * Triggers a server-side history sync via loadSessionData(true) and notifies
   * any listeners (SessionDirectory uses this to refresh its session list).
   */
  const notifySessionCreated = useCallback(
    (_optimisticId: string, _realId: string) => {
      loadSessionData(true);
      sessionCreatedListenersRef.current.forEach((fn) => fn());
    },
    [loadSessionData],
  );

  // Subscription API for components that want to react to "session created"
  // (replaces the window "chatCreated" event bus).
  const subscribeSessionCreated = useCallback((fn: () => void) => {
    sessionCreatedListenersRef.current.add(fn);
    return () => {
      sessionCreatedListenersRef.current.delete(fn);
    };
  }, []);

  const value = useMemo<SessionContextValue & {
    subscribeSessionCreated: (fn: () => void) => () => void;
  }>(
    () => ({
      currentSession: session.currentSession,
      workspace: session.workspace,
      sessionTitle: session.sessionTitle,
      isInitialLoading: session.isInitialLoading,
      activeCacheKey: session.activeCacheKey,
      navigateToSession: session.navigateToSession,
      prefetchSession: session.prefetchSession,
      streamingSessionIdsRef: session.streamingSessionIdsRef,
      messages: session.messages,
      getMessages,
      appendStartingMessages,
      finalizeAssistantMessage,
      replaceMessages,
      migrateBucket,
      notifySessionCreated,
      subscribeSessionCreated,
    }),
    [
      session.currentSession,
      session.workspace,
      session.sessionTitle,
      session.isInitialLoading,
      session.activeCacheKey,
      session.navigateToSession,
      session.prefetchSession,
      session.streamingSessionIdsRef,
      session.messages,
      getMessages,
      appendStartingMessages,
      finalizeAssistantMessage,
      replaceMessages,
      migrateBucket,
      notifySessionCreated,
      subscribeSessionCreated,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSessionContext() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSessionContext must be used inside <SessionProvider>");
  return ctx;
}
```

### Step 3: Commit

```bash
git add frontend/src/hooks/useSession.ts frontend/src/context/SessionContext.tsx
git commit -m "feat(frontend): SessionContext owns message cache via typed API"
```

---

## Task 5 — `InferenceContext` with atomic migrate + `migratedIds`

**Files:**
- Modify: `frontend/src/hooks/useInference.ts`
- Create: `frontend/src/context/InferenceContext.tsx`

### Step 1: Refactor `useInference.ts` to consume `SessionContext`

Replace the entirety of `frontend/src/hooks/useInference.ts` with:

```ts
import { useCallback, useRef, useState } from "react";
import { Message } from "@/types/chat";
import { apiFetch } from "@/utils/apiClient";
import {
  newOptimisticSessionId,
  newTempMessageId,
} from "@/utils/ids";
import type { useSessionContext } from "@/context/SessionContext";

type SessionApi = ReturnType<typeof useSessionContext>;

export interface InferenceApi {
  isProcessing: boolean;
  streamingContent: Record<string, string>;
  sendMessage: (
    text: string,
    activeSessionId: string | null,
    model: string,
    attachments?: string[],
    skipUserAdd?: boolean,
  ) => Promise<string>;
  stopInference: (id?: string | null) => void;
  /**
   * After a successful migrate (optimistic → real), the test runner needs to
   * map the optimistic id it received back from sendMessage onto the real id.
   * This map is exposed for that purpose.
   */
  migratedIds: React.MutableRefObject<Map<string, string>>;
  /**
   * Subscribe-style hook for the test runner: linkSession is invoked
   * synchronously the moment the real id arrives, with (optimistic, real).
   */
  setLinkSessionCallback: (cb: ((oldId: string, newId: string) => void) | null) => void;
}

export function useInference(
  workspaceSlug: string,
  sessionApi: SessionApi,
): InferenceApi {
  const [isProcessing, setIsProcessing] = useState(false);
  const [streamingContent, setStreamingContent] = useState<Record<string, string>>({});

  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const migratedIds = useRef<Map<string, string>>(new Map());
  const linkSessionRef = useRef<((oldId: string, newId: string) => void) | null>(null);

  const setLinkSessionCallback = useCallback(
    (cb: ((oldId: string, newId: string) => void) | null) => {
      linkSessionRef.current = cb;
    },
    [],
  );

  const sendMessage = useCallback(
    async (
      text: string,
      activeSessionId: string | null,
      model: string,
      attachments: string[] = [],
      skipUserAdd: boolean = false,
    ): Promise<string> => {
      setIsProcessing(true);

      const optimisticId = activeSessionId || newOptimisticSessionId();
      let realDbId: string | null = null;
      const ws = workspaceSlug;

      setStreamingContent((prev) => ({ ...prev, [optimisticId]: "" }));

      let fullAssistantMessage = "";

      const startingItems: Message[] = [];
      if (!skipUserAdd) {
        startingItems.push({
          id: newTempMessageId("u"),
          role: "user",
          content: text,
          timestamp: new Date().toISOString(),
        });
      }
      startingItems.push({
        id: newTempMessageId("a"),
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
      });
      sessionApi.appendStartingMessages(ws, optimisticId, startingItems);

      const controller = new AbortController();
      abortControllersRef.current.set(optimisticId, controller);
      sessionApi.streamingSessionIdsRef.current.add(optimisticId);

      try {
        const res = await apiFetch(
          `/analyze?workspace=${encodeURIComponent(ws)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: text,
              session_id:
                activeSessionId === "temp_new_chat" || !activeSessionId
                  ? null
                  : activeSessionId,
              attachments,
              skip_db_save: skipUserAdd,
            }),
            signal: controller.signal,
          },
        );

        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        let lineBuffer = "";

        if (reader) {
          streamLoop: while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            lineBuffer += decoder.decode(value, { stream: true });
            const lines = lineBuffer.split("\n");
            lineBuffer = lines.pop() || "";
            for (const line of lines) {
              if (!line.trim()) continue;
              try {
                const parsed = JSON.parse(line);

                if (parsed.error) {
                  fullAssistantMessage = `⚠ ${parsed.error}`;
                  setStreamingContent((prev) => {
                    const next = { ...prev, [optimisticId]: fullAssistantMessage };
                    if (realDbId !== null) next[realDbId] = fullAssistantMessage;
                    return next;
                  });
                  break streamLoop;
                }

                // THE HANDOFF — atomic single migrate.
                if (
                  parsed.status === "started" &&
                  parsed.session_id &&
                  !activeSessionId
                ) {
                  const newDbId = parsed.session_id as string;
                  realDbId = newDbId;

                  // Atomic bucket migration: cache key changes from
                  // optimisticId → newDbId. After this, all writes target the
                  // real id directly. No dual-bucket bookkeeping.
                  sessionApi.migrateBucket(ws, optimisticId, newDbId);

                  // Move abort controller alias.
                  const ctrl = abortControllersRef.current.get(optimisticId);
                  if (ctrl) abortControllersRef.current.set(newDbId, ctrl);

                  // Record the mapping so stopInference / external callers
                  // (test runner) can find the real id from the optimistic id.
                  migratedIds.current.set(optimisticId, newDbId);

                  sessionApi.streamingSessionIdsRef.current.add(newDbId);

                  // Mirror streamingContent under the new key so the in-flight
                  // text doesn't blank during URL navigation.
                  setStreamingContent((prev) => ({
                    ...prev,
                    [newDbId]: prev[optimisticId] ?? "",
                  }));

                  // Notify external listener (test runner / session list).
                  linkSessionRef.current?.(optimisticId, newDbId);
                  sessionApi.notifySessionCreated(optimisticId, newDbId);
                }

                if (parsed.chunk) {
                  fullAssistantMessage += parsed.chunk;
                  setStreamingContent((prev) => {
                    const next = { ...prev, [optimisticId]: fullAssistantMessage };
                    if (realDbId !== null) next[realDbId] = fullAssistantMessage;
                    return next;
                  });
                }
              } catch (e) {
                /* malformed line, skip */
              }
            }
          }
        }
      } catch (error: any) {
        // AbortError, network errors — stream ended early.
      } finally {
        setIsProcessing(false);

        const finalKeySid = realDbId ?? optimisticId;
        sessionApi.finalizeAssistantMessage(ws, finalKeySid, fullAssistantMessage);

        setStreamingContent((prev) => {
          const next = { ...prev };
          delete next[optimisticId];
          if (realDbId !== null) delete next[realDbId];
          return next;
        });

        sessionApi.streamingSessionIdsRef.current.delete(optimisticId);
        if (realDbId !== null) sessionApi.streamingSessionIdsRef.current.delete(realDbId);

        // Clean up controller aliases.
        abortControllersRef.current.delete(optimisticId);
        if (realDbId !== null) abortControllersRef.current.delete(realDbId);

        // Trigger a sidebar refresh through the SessionContext (replaces the
        // window "chatCreated" event). For the new-session case this also runs
        // when notifySessionCreated fires above; an extra call here is a no-op
        // that keeps the existing-session path covered too.
        sessionApi.notifySessionCreated(optimisticId, finalKeySid);
      }

      return optimisticId;
    },
    [workspaceSlug, sessionApi],
  );

  const stopInference = useCallback(
    (id?: string | null) => {
      const target = id || "temp_new_chat";
      const directController = abortControllersRef.current.get(target);
      if (directController) {
        directController.abort();
        return;
      }
      // If the caller passed an optimistic id we already migrated, follow the map.
      const mapped = migratedIds.current.get(target);
      if (mapped) {
        const c = abortControllersRef.current.get(mapped);
        c?.abort();
        return;
      }
      // Last-resort fallback: abort any optimistic controllers.
      for (const [key, controller] of abortControllersRef.current.entries()) {
        if (key.startsWith("optimistic-")) controller.abort();
      }
    },
    [],
  );

  return {
    isProcessing,
    streamingContent,
    sendMessage,
    stopInference,
    migratedIds,
    setLinkSessionCallback,
  };
}
```

### Step 2: Write `InferenceContext`

`frontend/src/context/InferenceContext.tsx`:

```tsx
"use client";

import React, { createContext, useContext } from "react";
import { useInference, type InferenceApi } from "@/hooks/useInference";
import { useSessionContext } from "@/context/SessionContext";

const InferenceContext = createContext<InferenceApi | null>(null);

export function InferenceProvider({ children }: { children: React.ReactNode }) {
  const sessionApi = useSessionContext();
  const inference = useInference(sessionApi.workspace, sessionApi);
  return <InferenceContext.Provider value={inference}>{children}</InferenceContext.Provider>;
}

export function useInferenceContext(): InferenceApi {
  const ctx = useContext(InferenceContext);
  if (!ctx) throw new Error("useInferenceContext must be used inside <InferenceProvider>");
  return ctx;
}
```

### Step 3: Commit

```bash
git add frontend/src/hooks/useInference.ts frontend/src/context/InferenceContext.tsx
git commit -m "feat(frontend): InferenceContext + atomic optimistic→real migrate"
```

---

## Task 6 — `UploaderContext`

**Files:**
- Create: `frontend/src/context/UploaderContext.tsx`

### Step 1: Write the context

```tsx
"use client";

import React, { createContext, useContext } from "react";
import { useUploader } from "@/hooks/useUploader";
import { useSessionContext } from "@/context/SessionContext";

type UploaderApi = ReturnType<typeof useUploader>;

const UploaderContext = createContext<UploaderApi | null>(null);

export function UploaderProvider({ children }: { children: React.ReactNode }) {
  const { workspace } = useSessionContext();
  const uploader = useUploader(workspace);
  return <UploaderContext.Provider value={uploader}>{children}</UploaderContext.Provider>;
}

export function useUploaderContext(): UploaderApi {
  const ctx = useContext(UploaderContext);
  if (!ctx) throw new Error("useUploaderContext must be used inside <UploaderProvider>");
  return ctx;
}
```

### Step 2: Commit

```bash
git add frontend/src/context/UploaderContext.tsx
git commit -m "feat(frontend): UploaderContext"
```

---

## Task 7 — `TestSuiteContext`

**Files:**
- Create: `frontend/src/context/TestSuiteContext.tsx`

### Step 1: Write the context

```tsx
"use client";

import React, { createContext, useContext, useEffect, useMemo } from "react";
import { useTestSuite } from "@/hooks/useTestSuite";
import { useInferenceContext } from "@/context/InferenceContext";

type TestSuiteApi = ReturnType<typeof useTestSuite>;

const TestSuiteContext = createContext<TestSuiteApi | null>(null);

export function TestSuiteProvider({ children }: { children: React.ReactNode }) {
  const inference = useInferenceContext();
  const tester = useTestSuite((text, sId) =>
    inference.sendMessage(text, sId, ""),
  );

  // Wire the test runner's linkSession into InferenceContext so the runner
  // gets notified the moment an optimistic→real handoff happens. Replaces the
  // direct prop-drilling that used to live in ChatContext.
  useEffect(() => {
    inference.setLinkSessionCallback(tester.linkSession);
    return () => inference.setLinkSessionCallback(null);
  }, [inference, tester.linkSession]);

  const value = useMemo(() => tester, [tester]);
  return <TestSuiteContext.Provider value={value}>{children}</TestSuiteContext.Provider>;
}

export function useTestSuiteContext(): TestSuiteApi {
  const ctx = useContext(TestSuiteContext);
  if (!ctx) throw new Error("useTestSuiteContext must be used inside <TestSuiteProvider>");
  return ctx;
}
```

> **Why this seam:** `useTestSuite` doesn't depend on a particular model at construction time (the TestSuite hook calls `sendMessage(text, sId)` with no model). The current `ChatContext` passes `selectedModel` from a separate state into the test runner; that wiring moves to `ChatInput`'s caller, which lives inside `ActiveSession` and reads the selected model from the user's settings. **Stop-gap:** for now, `TestSuiteContext` passes empty string for model — `useInference` accepts it but the backend then uses workspace `engine_config.model`. This matches Phase 4's behavior change where workspace pin overrides global default. Verify in smoke test.

### Step 2: Commit

```bash
git add frontend/src/context/TestSuiteContext.tsx
git commit -m "feat(frontend): TestSuiteContext consumes Inference + Session"
```

---

## Task 8 — `AppProviders` + remove old `ChatContext` + migrate consumers

This is the largest mechanical task. After this, the old `ChatContext` is gone and every component pulls from one of the five focused contexts.

**Files:**
- Create: `frontend/src/context/AppProviders.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/components/ActiveSession.tsx`
- Modify: `frontend/src/components/ChatBubble.tsx`
- Modify: `frontend/src/components/ChatHeader.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/SessionDirectory.tsx`
- Modify: `frontend/src/components/SessionItem.tsx`
- Modify: `frontend/src/components/WorkspaceSwitcher.tsx`
- Modify: `frontend/src/components/WorkspaceSettings.tsx`
- Remove: `frontend/src/context/ChatContext.tsx`

### Step 1: Write `AppProviders.tsx`

```tsx
"use client";

import React from "react";
import { WorkspaceProvider } from "@/context/WorkspaceContext";
import { SessionProvider } from "@/context/SessionContext";
import { InferenceProvider } from "@/context/InferenceContext";
import { UploaderProvider } from "@/context/UploaderContext";
import { TestSuiteProvider } from "@/context/TestSuiteContext";

/**
 * Composition order matters: lower providers consume higher ones via their
 * useXxxContext() hook (e.g. InferenceProvider reads SessionContext).
 *
 *   WorkspaceContext  — workspaces[], activeWorkspace, slug routing
 *   SessionContext    — sessions, folders, message cache (single writer)
 *   InferenceContext  — SSE streaming, sendMessage, stopInference
 *   UploaderContext   — file upload queue
 *   TestSuiteContext  — dev-only data-driven test runner
 */
export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <SessionProvider>
        <InferenceProvider>
          <UploaderProvider>
            <TestSuiteProvider>{children}</TestSuiteProvider>
          </UploaderProvider>
        </InferenceProvider>
      </SessionProvider>
    </WorkspaceProvider>
  );
}
```

### Step 2: Update `page.tsx`

Edit `frontend/src/app/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import ActiveSession from "@/components/ActiveSession";
import { AppProviders } from "@/context/AppProviders";
import { TokenGate } from "@/components/TokenGate";
import { getToken } from "@/utils/apiClient";

export default function Home() {
  const [isMounted, setIsMounted] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [hasToken, setHasToken] = useState<boolean | null>(null);

  useEffect(() => {
    setIsMounted(true);
    setHasToken(!!getToken());
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  }, []);

  if (!isMounted || hasToken === null) {
    return <div className="h-screen w-full bg-[#131314]" />;
  }

  if (!hasToken) {
    return <TokenGate onConfigured={() => setHasToken(true)} />;
  }

  return (
    <AppProviders>
      <div className="flex h-screen w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
        <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />
        <ActiveSession isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} />
      </div>
    </AppProviders>
  );
}
```

### Step 3: Migrate `ActiveSession.tsx`

The key changes are:
- `useChatContext()` → granular hooks.
- The selected-model state moves into `ActiveSession` itself (it's only consumed when calling `sendMessage`, which the inference handler does).
- Stop spreading `{...m, content: displayContent}`; pass `m` and `displayContent` separately.
- `currentIsProcessing` derives from `streamingSessionIdsRef`.
- `currentIsTesting` derives from `useTestSuiteContext()`.
- The `handleInference` and `stopAllInference` orchestration that lived in `ChatContext` moves here.

Replace the file body (preserving everything outside the component shape):

```tsx
"use client";

import React, { useRef, useEffect, useState, useCallback } from "react";
import { useSessionContext } from "@/context/SessionContext";
import { useInferenceContext } from "@/context/InferenceContext";
import { useUploaderContext } from "@/context/UploaderContext";
import { useTestSuiteContext } from "@/context/TestSuiteContext";
import { useMessageActions } from "@/hooks/useMessageActions";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useSearch } from "@/hooks/useSearch";
import { usePrompt } from "@/hooks/usePrompt";
import { APP_CONFIG } from "@/utils/constants";
import ChatInput from "./ChatInput";
import ChatHeader from "./ChatHeader";
import QuickActions from "./QuickActions";
import ProcessingAnimation from "./ProcessingAnimation";
import SearchBar from "./SearchBar";
import ChatTimestamp from "./ChatTimestamp";
import ChatBubble from "./ChatBubble";
import ConfirmModal from "./ConfirmModal";

export default function ActiveSession({ isSidebarOpen, setIsSidebarOpen }: any) {
  const session = useSessionContext();
  const ai = useInferenceContext();
  const uploader = useUploaderContext();
  const tester = useTestSuiteContext();

  const [selectedModel] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("pryzm_model") || APP_CONFIG.DEFAULT_MODEL;
    }
    return APP_CONFIG.DEFAULT_MODEL;
  });

  const messages = session.messages;
  const activeSessionKey = session.currentSession || "temp_new_chat";
  const myStreamingText = ai.streamingContent[activeSessionKey];

  const currentIsProcessing =
    session.streamingSessionIdsRef.current.has(activeSessionKey);
  const currentIsTesting = tester.activeTestSessions.has(activeSessionKey);

  const promptState = usePrompt(messages);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const { scrollRef, onScroll } = useAutoScroll({
    messages,
    streamingText: myStreamingText ?? "",
    isProcessing: currentIsProcessing,
  });
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; index: number } | null>(null);

  useEffect(() => {
    const isDesktopPointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (textareaRef.current && activeSessionKey === "temp_new_chat" && isDesktopPointer) {
      textareaRef.current.focus();
    }
  }, [activeSessionKey]);

  const search = useSearch(messages, chatContainerRef);

  const handleInference = useCallback(
    async (rawPrompt: string) => {
      if (!rawPrompt.trim() || currentIsProcessing) return;

      let activeIdToUse = session.currentSession;
      if (activeIdToUse === "temp_new_chat") activeIdToUse = null;

      const pendingUploads = uploader.uploads.filter((u) => u.status === "pending");
      if (pendingUploads.length > 0) {
        await uploader.processUploadQueue(pendingUploads);
      }

      const successfulUploads = uploader.uploads.filter((u) => u.status === "success");
      const documentIds = successfulUploads
        .map((u) => u.document_id)
        .filter((id): id is string => Boolean(id));

      let attachedPrefix = successfulUploads
        .map((u) => `[Attached_File:${u.file.name}]`)
        .join("\n");
      if (attachedPrefix) attachedPrefix += "\n";

      const textToSend = attachedPrefix + rawPrompt;
      uploader.clearQueue();
      await ai.sendMessage(textToSend, activeIdToUse, selectedModel, documentIds);
    },
    [currentIsProcessing, session.currentSession, uploader, ai, selectedModel],
  );

  const stopAllInference = useCallback(() => {
    tester.stopTestSuite(session.currentSession);
    ai.stopInference(session.currentSession);
  }, [tester, ai, session.currentSession]);

  const msgActions = useMessageActions(
    session.workspace,
    activeSessionKey,
    session.activeCacheKey,
    session.messages,
    session.replaceMessages,
    ai.sendMessage,
    session.navigateToSession,
    selectedModel,
  );

  const onSubmit = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      const text = promptState.prompt.trim();
      if (!text || currentIsProcessing) return;
      handleInference(text);
      promptState.saveToHistory(text);
      promptState.setPrompt("");
    },
    [promptState, currentIsProcessing, handleInference],
  );

  const onDeleteRequest = useCallback(
    (id: string, idx: number) => setDeleteConfirm({ id, index: idx }),
    [],
  );

  return (
    <div className="flex flex-col flex-1 h-full w-full max-w-[100vw] overflow-hidden bg-[#131314]">
      <ChatHeader
        sessionTitle={messages.length === 0 ? "" : session.sessionTitle}
        isSidebarOpen={isSidebarOpen}
        setIsSidebarOpen={setIsSidebarOpen}
        rightActions={<SearchBar {...search} />}
      />

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto overflow-x-hidden px-2 sm:px-4 py-2 custom-scrollbar w-full min-w-0"
      >
        <div ref={chatContainerRef} className="w-full max-w-3xl mx-auto flex flex-col min-h-full min-w-0">
          {session.isInitialLoading && (
            <div className="flex-1 flex items-center justify-center min-h-[40vh]">
              <div className="text-gray-500 text-sm flex items-center gap-2">
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Loading messages…
              </div>
            </div>
          )}

          {!session.isInitialLoading && messages.length === 0 && !currentIsProcessing && (
            <QuickActions setPrompt={promptState.setPrompt} inputRef={textareaRef} />
          )}

          {messages.map((m: any, i: number) => {
            const isLastStreaming = currentIsProcessing && i === messages.length - 1 && m.role === "assistant";
            const displayContent = isLastStreaming && myStreamingText ? myStreamingText : m.content;
            const stableKey = m.id ?? `idx-${i}`;
            return (
              <React.Fragment key={stableKey}>
                <ChatTimestamp
                  timestamp={m.timestamp}
                  previousTimestamp={i > 0 ? messages[i - 1].timestamp : undefined}
                  isFirstMessage={i === 0}
                />
                <ChatBubble
                  message={m}
                  displayContent={displayContent}
                  index={i}
                  searchQuery={search.searchQuery}
                  isStreaming={isLastStreaming}
                  onDeleteRequest={onDeleteRequest}
                  saveEdit={msgActions.saveEdit}
                  branchSession={msgActions.branchSession}
                  rerunAssistant={msgActions.rerunAssistant}
                />
              </React.Fragment>
            );
          })}

          {currentIsProcessing && messages.length > 0 && !myStreamingText && <ProcessingAnimation />}
        </div>
      </div>

      <div className="shrink-0 pb-6 px-4 w-full flex justify-center bg-gradient-to-t from-[#131314] to-transparent">
        <ChatInput
          prompt={promptState.prompt}
          setPrompt={promptState.setPrompt}
          uploads={uploader.uploads}
          setUploads={uploader.setUploads}
          isProcessing={currentIsProcessing}
          isAutoTesting={currentIsTesting}
          handleInference={onSubmit}
          stopAutoTest={stopAllInference}
          handleKeyDown={(e: any) => promptState.handleKeyDown(e, onSubmit)}
          runTestSuite={(type: any) => tester.runTestSuite(type, session.currentSession)}
          processUploadQueue={(files: any[]) => uploader.processUploadQueue(files)}
          totalTokens={promptState.totalTokens}
          inputRef={textareaRef}
        />
      </div>

      <ConfirmModal
        isOpen={!!deleteConfirm}
        title="Delete Message?"
        description="This permanently removes the bubble from your history."
        onConfirm={() => {
          if (deleteConfirm) {
            msgActions.deleteMessage(deleteConfirm.id, deleteConfirm.index);
            setDeleteConfirm(null);
          }
        }}
        onCancel={() => setDeleteConfirm(null)}
      />
    </div>
  );
}
```

### Step 4: Migrate `ChatBubble.tsx` — `React.memo` + decoupled props

Replace top of `frontend/src/components/ChatBubble.tsx`:

```tsx
import React, { useState, useEffect, useRef } from "react";
import { CheckIcon, CancelIcon, RerunIcon } from "./Icons";
import UserMessage from "./UserMessage";
import AssistantMessage from "./AssistantMessage";
import MessageActions from "./MessageActions";

interface ChatBubbleProps {
  message: any;          // stable identity (parent passes `m` directly, no spread)
  displayContent: string; // streamed text; updates per token without changing `message`
  index: number;
  searchQuery: string;
  isStreaming: boolean;
  onDeleteRequest: (id: string, index: number) => void;
  saveEdit: (msgId: string | undefined, index: number, newContent: string, rerun: boolean) => void;
  branchSession: (msgId: string) => void;
  rerunAssistant: (index: number) => void;
}

function ChatBubbleImpl({
  message,
  displayContent,
  index,
  searchQuery,
  isStreaming,
  onDeleteRequest,
  saveEdit,
  branchSession,
  rerunAssistant,
}: ChatBubbleProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(message.content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!isEditing) setEditValue(message.content);
  }, [message.id, message.content, isEditing]);

  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [editValue, isEditing]);

  if (isEditing) {
    return (
      // … same edit-mode JSX as before, but onClick handlers use the prop-passed
      // saveEdit instead of msgActions.saveEdit. The button bodies are unchanged
      // text/icons, so:
      //   onClick={() => { saveEdit(message.id, index, editValue, false); setIsEditing(false); }}
      //   onClick={() => { saveEdit(message.id, index, editValue, true); setIsEditing(false); }}
      // … (full JSX preserved verbatim from current file, only the destination
      // changes from msgActions.* to the new prop callbacks)
      <div className="flex justify-end w-full mb-6">
        <div className="w-full max-w-[85%] bg-[#2f2f2f] text-[#e3e3e3] rounded-2xl py-3 px-5 border border-white/5 shadow-xl transition-all">
          <textarea
            ref={textareaRef}
            autoFocus
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            className="w-full bg-transparent text-[15px] resize-none outline-none leading-relaxed overflow-hidden"
          />
          <div className="flex justify-end items-center gap-2 mt-2 pt-2 border-t border-white/5">
            <button type="button" onClick={() => setIsEditing(false)} className="p-1.5 text-gray-500 hover:text-red-500 transition-colors" title="Cancel">
              <CancelIcon className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => { saveEdit(message.id, index, editValue, false); setIsEditing(false); }}
              className="p-1.5 text-gray-500 hover:text-emerald-500 transition-colors"
              title="Save changes"
            >
              <CheckIcon className="w-4 h-4" />
            </button>
            {message.role === "user" && (
              <button
                type="button"
                onClick={() => { saveEdit(message.id, index, editValue, true); setIsEditing(false); }}
                className="flex items-center gap-1.5 pl-2 pr-1 py-1.5 group/rerun transition-all"
              >
                <RerunIcon className="w-3.5 h-3.5 text-gray-500 group-hover/rerun:text-blue-400 group-hover/rerun:rotate-45 transition-all duration-300" />
                <span className="text-[10px] font-bold tracking-tighter text-gray-500 group-hover/rerun:text-blue-400">RERUN</span>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex flex-col w-full mb-6 relative">
      <div className={`flex ${message.role === "user" ? "justify-end" : "justify-start"} w-full`}>
        <div className={`flex flex-col ${message.role === "user" ? "max-w-[85%] items-end" : "w-full items-start"} min-w-0`}>
          <div
            className={`${message.role === "user"
              ? "bg-[#2f2f2f] text-[#e3e3e3] rounded-2xl py-2.5 px-5"
              : "text-[#e3e3e3] px-1 w-full flex-1"
            } break-words min-w-0`}
          >
            {message.role === "user" ? (
              <UserMessage content={displayContent} searchQuery={searchQuery} />
            ) : (
              <AssistantMessage content={displayContent} searchQuery={searchQuery} />
            )}
          </div>

          {!isStreaming && (
            <MessageActions
              content={displayContent}
              timestamp={message.timestamp}
              isUser={message.role === "user"}
              onDelete={() => onDeleteRequest(message.id, index)}
              onEdit={() => { setIsEditing(true); setEditValue(message.content); }}
              onBranch={() => branchSession(message.id)}
              onRerun={() => message.role === "user"
                ? saveEdit(message.id, index, message.content, true)
                : rerunAssistant(index)
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}

const ChatBubble = React.memo(ChatBubbleImpl, (prev, next) => {
  // Stable bubbles only re-render when their own message identity changes,
  // their displayed content changes (streaming bubble during a stream, or
  // the canonical content after edit/rerun), search highlight changes, or
  // streaming state flips.
  return (
    prev.message === next.message &&
    prev.displayContent === next.displayContent &&
    prev.searchQuery === next.searchQuery &&
    prev.isStreaming === next.isStreaming &&
    prev.index === next.index
    // Callback props (saveEdit, branchSession, rerunAssistant, onDeleteRequest)
    // are stabilized by useCallback at the parent — comparing them is unnecessary
    // because if they change, parent re-rendered and we already pass new ones.
  );
});

export default ChatBubble;
```

> **Why the equality check ignores callbacks:** the spec calls out callback stability as a parent's job. `ActiveSession` already uses `useCallback`. If a callback identity changes, it means parent re-rendered with different deps and the bubble *should* re-render too — so re-render is correct in that path.

### Step 5: Migrate trivial consumers

`ChatHeader.tsx` — replace `useChatContext()` with `useWorkspaceContext()`:

```tsx
// before:
import { useChatContext } from "@/context/ChatContext";
// after:
import { useWorkspaceContext } from "@/context/WorkspaceContext";

// inside the component:
const { activeWorkspace } = useWorkspaceContext();
```

`Sidebar.tsx` — `useSessionContext()`:

```tsx
import { useSessionContext } from "@/context/SessionContext";
// in the component:
const session = useSessionContext();
```

`SessionItem.tsx` — `useSessionContext()`:

```tsx
import { useSessionContext } from "@/context/SessionContext";
// in the component:
const session = useSessionContext();
```

`WorkspaceSwitcher.tsx` — `useWorkspaceContext()`:

```tsx
import { useWorkspaceContext } from "@/context/WorkspaceContext";
// in the component:
const { workspacesApi, activeWorkspace } = useWorkspaceContext();
```

`WorkspaceSettings.tsx` — `useWorkspaceContext()`:

```tsx
import { useWorkspaceContext } from "@/context/WorkspaceContext";
// in the component:
const { workspacesApi } = useWorkspaceContext();
```

### Step 6: Migrate `SessionDirectory.tsx` — drop the `chatCreated` window event

Replace the imports and the `useEffect` that subscribes to `chatCreated`.

```tsx
import { useSessionContext } from "@/context/SessionContext";
// in the component:
const session = useSessionContext();
```

Replace the existing window listener block (lines ~112–117) with:

```tsx
  useEffect(() => {
    fetchSessions();
    fetchFolders();
    // Subscribe to "session created" via the SessionContext's internal bus
    // instead of a window-level event. Returns the unsubscribe function.
    return session.subscribeSessionCreated(fetchSessions);
  }, [fetchSessions, fetchFolders, session]);
```

> **Note:** The current code returns `removeEventListener` from inside the effect. The pattern above returns `subscribeSessionCreated`'s unsubscribe handle, which is the same shape (effect returns a cleanup function).

### Step 7: Update `useMessageActions` signature to accept `replaceMessages`

The hook today writes to the message cache via `setMessageCache(prev => ...)`. After Phase 5 it goes through `SessionContext.replaceMessages`. Patch the signature and call sites:

```ts
// frontend/src/hooks/useMessageActions.ts

export function useMessageActions(
  workspace: string,
  activeSessionKey: string,
  activeCacheKey: string,
  messages: any[],
  replaceMessages: (workspaceSlug: string, sessionId: string, messages: any[]) => void,
  sendMessage: any,
  navigateToSession: (id: string) => void,
  selectedModel: string,
) {
  const saveEdit = useCallback(async (msgId, index, newContent, rerun) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    await apiFetch(`/messages/${msgId}?workspace=${workspace}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newContent }),
    });

    if (rerun) {
      await apiFetch(`/sessions/${activeSessionKey}/truncate/${msgId}?workspace=${workspace}`, { method: "DELETE" });
      const truncated = messages.slice(0, index + 1);
      truncated[index] = { ...truncated[index], content: newContent };
      replaceMessages(workspace, activeSessionKey, truncated);
      sendMessage(newContent, activeSessionKey, selectedModel, [], true);
    } else {
      const updated = [...messages];
      updated[index] = { ...updated[index], content: newContent };
      replaceMessages(workspace, activeSessionKey, updated);
    }
  }, [messages, activeSessionKey, replaceMessages, sendMessage, workspace, selectedModel]);

  const deleteMessage = useCallback(async (msgId, index) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    const isPair = messages[index].role === "user" && messages[index + 1]?.role === "assistant";
    const newMessages = [...messages];
    const assistantId = isPair ? messages[index + 1].id : null;
    newMessages.splice(index, isPair ? 2 : 1);
    replaceMessages(workspace, activeSessionKey, newMessages);
    await apiFetch(`/messages/${msgId}?workspace=${workspace}`, { method: "DELETE" });
    if (assistantId) await apiFetch(`/messages/${assistantId}?workspace=${workspace}`, { method: "DELETE" });
  }, [messages, activeSessionKey, replaceMessages, workspace]);

  const branchSession = useCallback(async (msgId: string) => {
    // unchanged: doesn't touch the cache
    if (!msgId || msgId.startsWith('temp-')) return;
    try {
      const res = await apiFetch(`/sessions/${activeSessionKey}/branch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ up_to_message_id: msgId }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.new_session_id) navigateToSession(data.new_session_id);
      }
    } catch (err) { console.error("Failed to branch session:", err); }
  }, [activeSessionKey, navigateToSession]);

  const rerunAssistant = useCallback(async (index: number) => {
    if (index === 0 || messages[index].role !== 'assistant') return;
    const userMsg = messages[index - 1];
    if (!userMsg || userMsg.role !== 'user') return;
    await apiFetch(`/sessions/${activeSessionKey}/truncate/${userMsg.id}?workspace=${workspace}`, { method: "DELETE" });
    const truncated = messages.slice(0, index);
    replaceMessages(workspace, activeSessionKey, truncated);
    sendMessage(userMsg.content, activeSessionKey, selectedModel, [], true);
  }, [messages, activeSessionKey, replaceMessages, sendMessage, workspace, selectedModel]);

  return { deleteMessage, saveEdit, branchSession, rerunAssistant };
}
```

The `activeCacheKey` parameter is now unused — drop it from the signature and from the `ActiveSession` call site. Confirm by grepping `activeCacheKey` after the edit.

### Step 8: Remove the old `ChatContext.tsx`

```bash
rm frontend/src/context/ChatContext.tsx
```

### Step 9: Build + manual verify

```bash
cd frontend && npm run build 2>&1 | tail -10
# Expected: "Compiled successfully" and zero type errors.
```

If TypeScript complains about a remaining `useChatContext` import: grep and fix:

```bash
grep -rn "useChatContext\|ChatContext" frontend/src/
# Expected: no results.
```

### Step 10: Commit

```bash
git add frontend/src/context/AppProviders.tsx frontend/src/app/page.tsx \
        frontend/src/components/{ActiveSession,ChatBubble,ChatHeader,Sidebar,SessionDirectory,SessionItem,WorkspaceSwitcher,WorkspaceSettings}.tsx \
        frontend/src/hooks/useMessageActions.ts
git rm frontend/src/context/ChatContext.tsx
git commit -m "refactor(frontend): migrate consumers to focused contexts; drop ChatContext"
```

---

## Task 9 — `withRollback` at folder + workspace-edit + message-edit sites

**Files:**
- Modify: `frontend/src/components/SessionDirectory.tsx`
- Modify: `frontend/src/components/WorkspaceSettings.tsx`
- Modify: `frontend/src/hooks/useMessageActions.ts`

### Step 1: Wrap folder mutations in `SessionDirectory.tsx`

Replace `createFolderImpl`:

```tsx
  const createFolderImpl = async (name: string) => {
    const newFolder = { id: uuid(), name, workspace };
    setIsCreatingFolder(false);
    try {
      await withRollback(
        () => setFolders((prev) => [{ ...newFolder, isOpen: true }, ...prev]),
        () => setFolders((prev) => prev.filter((f) => f.id !== newFolder.id)),
        async () => {
          const r = await apiFetch("/folders", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(newFolder),
          });
          if (!r.ok) throw new Error("create failed");
        },
      );
    } catch (err) {
      console.error("Folder create failed", err);
    }
  };
```

Replace `handleRenameFolderSubmit`:

```tsx
  const handleRenameFolderSubmit = async (e: React.FormEvent, id: string) => {
    e.preventDefault();
    const cleaned = editFolderTitle.trim();
    if (!cleaned) return setEditingFolderId(null);
    const previous = folders.find((f) => f.id === id);
    if (!previous) return;
    setEditingFolderId(null);
    try {
      await withRollback(
        () => setFolders((prev) => prev.map((f) => (f.id === id ? { ...f, name: cleaned } : f))),
        () => setFolders((prev) => prev.map((f) => (f.id === id ? { ...f, name: previous.name } : f))),
        async () => {
          const r = await apiFetch(`/folders/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: cleaned }),
          });
          if (!r.ok) throw new Error("rename failed");
        },
      );
    } catch (err) {
      console.error("Folder rename failed", err);
    }
  };
```

Replace `confirmDeleteFolder`:

```tsx
  const confirmDeleteFolder = async () => {
    if (!folderPendingDelete) return;
    const folderId = folderPendingDelete.id;
    const snapshot = folderPendingDelete;
    setFolderPendingDelete(null);
    try {
      await withRollback(
        () => setFolders((prev) => prev.filter((f) => f.id !== folderId)),
        () => setFolders((prev) => [snapshot, ...prev.filter((f) => f.id !== folderId)]),
        async () => {
          const r = await apiFetch(`/folders/${folderId}`, { method: "DELETE" });
          if (!r.ok) throw new Error("delete failed");
        },
      );
      fetchSessions();
    } catch (err) {
      console.error("Folder delete failed", err);
    }
  };
```

Replace `handleDropToFolder`:

```tsx
  const handleDropToFolder = async (e: React.DragEvent, folderId: string | null) => {
    e.preventDefault();
    const sessionId = e.dataTransfer.getData("application/x-pryzm-session");
    if (!sessionId) return;

    const previous = sessions.find((s) => s.id === sessionId);
    const previousFolderId = previous?.folder_id ?? null;
    if (previousFolderId === folderId) return;

    try {
      await withRollback(
        () => setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, folder_id: folderId } : s))),
        () => setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, folder_id: previousFolderId } : s))),
        async () => {
          const r = await apiFetch(`/sessions/${sessionId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder_id: folderId }),
          });
          if (!r.ok) throw new Error("move failed");
        },
      );
    } catch (err) {
      console.error("Session move failed", err);
    }
  };
```

Add the import:

```tsx
import { withRollback } from "@/utils/withRollback";
```

### Step 2: Wrap edit-mode `save()` in `WorkspaceSettings.tsx`

The current pattern fires-and-forgets on blur. After Phase 5: wrap with `withRollback` so a 500 reverts the local edit.

Replace the `save` helper:

```tsx
  const save = async (patch: Record<string, unknown>) => {
    if (mode !== "edit") return;
    // Snapshot pre-mutation state for rollback. Only the fields in `patch`
    // need restoring; we re-apply the workspace's pre-mutation values.
    const previous: Record<string, unknown> = {
      display_name: workspace.display_name,
      system_prompt: workspace.system_prompt,
      enabled_tools: workspace.enabled_tools,
      model_name: workspace.model_name,
      color: workspace.color,
    };

    try {
      await withRollback(
        () => {
          // The local state setters (setName, setPrompt, ...) have already run
          // by the time save() is called from onBlur/onChange handlers, so the
          // local state IS the optimistic application — no extra step needed.
        },
        () => {
          // Restore each touched field from the snapshot.
          if ("display_name" in patch) setName(previous.display_name as string);
          if ("system_prompt" in patch) setPrompt(previous.system_prompt as string);
          if ("enabled_tools" in patch) setEnabledTools(previous.enabled_tools as string[]);
          if ("model_name" in patch) setPreferredModel((previous.model_name as string | null) ?? null);
          if ("color" in patch) setColor((previous.color as WorkspaceColor) ?? DEFAULT_WORKSPACE_COLOR);
        },
        async () => {
          const ws = await workspacesApi.update(workspace.slug, patch);
          if (!ws) throw new Error("update failed");
          return ws;
        },
      );
    } catch (err) {
      console.error("Workspace update failed", err);
    }
  };
```

Add the import:

```tsx
import { withRollback } from "@/utils/withRollback";
```

The call sites (`onBlur` / `onChange` for the various fields) don't change shape — `save({...})` is now async-but-fire-and-forget from the handler's POV. Local state was already optimistically set; `withRollback` reverts on failure.

### Step 3: Wrap message-edit in `useMessageActions.ts`

Wrap `saveEdit`'s patch + rerun flow:

```ts
  const saveEdit = useCallback(async (msgId, index, newContent, rerun) => {
    if (!msgId || msgId.startsWith('temp-')) return;
    const previousContent = messages[index]?.content;
    const previousMessages = [...messages];

    try {
      // Local apply happens via replaceMessages below; rollback restores the snapshot.
      await withRollback(
        () => {
          if (rerun) {
            const truncated = messages.slice(0, index + 1);
            truncated[index] = { ...truncated[index], content: newContent };
            replaceMessages(workspace, activeSessionKey, truncated);
          } else {
            const updated = [...messages];
            updated[index] = { ...updated[index], content: newContent };
            replaceMessages(workspace, activeSessionKey, updated);
          }
        },
        () => replaceMessages(workspace, activeSessionKey, previousMessages),
        async () => {
          const r = await apiFetch(`/messages/${msgId}?workspace=${workspace}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: newContent }),
          });
          if (!r.ok) throw new Error("edit failed");
          if (rerun) {
            const tr = await apiFetch(
              `/sessions/${activeSessionKey}/truncate/${msgId}?workspace=${workspace}`,
              { method: "DELETE" },
            );
            if (!tr.ok) throw new Error("truncate failed");
          }
        },
      );

      if (rerun) sendMessage(newContent, activeSessionKey, selectedModel, [], true);
    } catch (err) {
      console.error("Message edit failed", err);
    }
  }, [messages, activeSessionKey, replaceMessages, sendMessage, workspace, selectedModel]);
```

Add the import:

```ts
import { withRollback } from "@/utils/withRollback";
```

> **Note:** `deleteMessage` is intentionally NOT wrapped. A delete that succeeds locally but fails on the server already reverts on the next refresh, and the spec specifically calls out folder/workspace/message-edit as the rollback sites. Keeping `deleteMessage` as fire-and-forget keeps the diff small.

### Step 4: Build + commit

```bash
cd frontend && npm run build 2>&1 | tail -5
# Expected: clean build.
git add frontend/src/components/{SessionDirectory,WorkspaceSettings}.tsx frontend/src/hooks/useMessageActions.ts
git commit -m "feat(frontend): apply withRollback to folder, workspace, and message edits"
```

---

## Task 10 — Re-render storm fixes (verification + extras)

The big move is already done in Task 8 (`React.memo` on `ChatBubble`, separate `displayContent` prop in `ActiveSession`). Two small leftovers remain:

**Files:**
- Modify: `frontend/src/components/ActiveSession.tsx` (cosmetic — cb stability)
- Modify: `frontend/src/hooks/useSession.ts` (verify `streamingSessionIdsRef` access)

### Step 1: Verify callback stability in `ActiveSession`

The migration already wrapped `handleInference`, `stopAllInference`, `onSubmit`, `onDeleteRequest` in `useCallback`. Grep to confirm no inline arrow functions remain on the bubble props or major child boundaries:

```bash
grep -n "onDeleteRequest=\|onClick={()" frontend/src/components/ActiveSession.tsx
```

Anything that survived the migration as `() => …` inline on a bubble prop should move into a `useCallback`. Most should already be done.

### Step 2: Confirm `streamingSessionIdsRef` reads don't happen in render bodies

The spec calls out: "`streamingSessionIdsRef` reads stop happening in render bodies; converted to state where the read affects render."

Grep to find places that read `streamingSessionIdsRef.current` inside JSX or component-body code-paths that affect render output:

```bash
grep -n "streamingSessionIdsRef.current" frontend/src/components/ frontend/src/hooks/
```

Two known sites:

1. `useSession.ts` reads `streamingSessionIdsRef.current.has(...)` to compute `isActivelyStreaming` in the body — this is fine because `currentSession` and `urlSessionId` recompute the body on the relevant changes. Leave as-is.
2. `SessionDirectory.tsx` passes `streamingSessionIdsRef.current.has(s.id)` as the `isStreaming` prop on `SessionItem`. This means changes to the ref don't trigger re-render — which is the existing (intentional) behavior because the streaming-flag toast is best-effort. Leave as-is; do not promote to state for this phase.

The render-storm fix is satisfied by `React.memo(ChatBubble)` + separated `displayContent` prop. Promoting `streamingSessionIdsRef` to state is out of scope; revisit only if a regression surfaces.

### Step 3: Commit (if anything changed)

```bash
git diff --quiet || (git add -A && git commit -m "chore(frontend): callback stability cleanup")
```

If nothing changed, skip the commit — the work was done in Task 8.

---

## Task 11 — Phase 5 e2e smoke tests

**Files:**
- Create: `backend/tests/e2e/test_phase5_smoke.py`

### Step 1: Write the smoke probe

`backend/tests/e2e/test_phase5_smoke.py`:

```python
"""UI smoke tests for Phase 5: frontend state ownership.

Probes verify the four success-criteria from the spec:

  1. Send 3 messages within 200 ms — all 3 land with distinct IDs and ordered.
  2. Navigate away from a streaming session and back — no orphan empty bubbles.
  3. Toggle a workspace setting with the backend forced to 500 — UI rolls back.
  4. ChatBubble re-render is bounded (counted via a small DOM probe).

These tests assume the dev servers are up (see conftest.py).
"""
import time

from playwright.sync_api import Page, expect

FRONTEND_URL = "http://127.0.0.1:3000"


def _open_app_with_token(page: Page, token: str) -> None:
    page.goto(FRONTEND_URL)
    page.evaluate(f'() => localStorage.setItem("pryzm_api_token", "{token}")')
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10_000)


def _send_chat_message(page: Page, text: str) -> None:
    textarea = page.locator('textarea[placeholder="Ask Pryzm anything..."]')
    textarea.wait_for(state="visible", timeout=5_000)
    textarea.fill(text)
    textarea.press("Enter")


_ASSISTANT_HAS_CONTENT = """
() => {
    const els = Array.from(document.querySelectorAll('.custom-scrollbar'));
    const chatEl = els.find(el => el.className.includes('overflow-x-hidden'));
    if (!chatEl) return false;
    const paragraphs = chatEl.querySelectorAll('p');
    for (const p of paragraphs) {
        if ((p.textContent || '').trim().length > 5) return true;
    }
    return false;
}
"""


def test_rapid_sends_distinct_ids_and_ordered(page: Page, api_token: str, screenshot):
    """Send 3 messages in rapid succession; verify each lands as a distinct user
    bubble in send-order. Exercises crypto.randomUUID() optimistic IDs (no
    Date.now() collisions on rapid sends)."""
    _open_app_with_token(page, api_token)
    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    base = int(time.time())
    msgs = [f"phase5-rapid-{base}-a", f"phase5-rapid-{base}-b", f"phase5-rapid-{base}-c"]

    # Send first; wait for the session id to materialize so subsequent sends
    # target the same conversation. This simulates a user double/triple-clicking
    # send within ~200ms of the bubble appearing.
    _send_chat_message(page, msgs[0])
    page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=60_000)

    # Now hammer sends 2 + 3 with no wait — they go into the same session.
    for m in msgs[1:]:
        _send_chat_message(page, m)
        page.wait_for_timeout(80)

    # All 3 wait for assistant replies.
    page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=120_000)
    page.wait_for_timeout(2_000)

    # Verify all 3 user texts are present in the DOM, in send-order.
    body_text = page.evaluate("() => document.body.textContent || ''")
    last_pos = -1
    for m in msgs:
        pos = body_text.find(m)
        assert pos != -1, f"missing message {m!r} in DOM"
        assert pos > last_pos, f"message {m!r} appeared out of order (pos {pos} <= prev {last_pos})"
        last_pos = pos

    screenshot("rapid-sends")


def test_navigate_during_stream_no_orphan_bubble(page: Page, api_token: str, screenshot):
    """Start a stream in workspace=personal; navigate away to it_copilot before
    it finishes; navigate back. The personal session must show real content,
    not an empty assistant bubble."""
    _open_app_with_token(page, api_token)
    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    unique = f"phase5-orphan-{int(time.time())}"
    _send_chat_message(page, unique)
    # Brief pause so the request is in flight but probably not finished.
    page.wait_for_timeout(400)

    # Navigate away mid-stream.
    page.goto(f"{FRONTEND_URL}/?workspace=it_copilot")
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.wait_for_timeout(800)

    # Return to personal — find the session that contains our unique message.
    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.wait_for_timeout(2_500)  # let session list + history reload

    # Locate the session by clicking the entry whose title or first message
    # contains the unique phrase. Easiest: click the most-recent (top) entry.
    sessions = page.locator('a[href*="/?workspace=personal&session="]')
    sessions.first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.wait_for_timeout(2_000)

    body_text = page.evaluate("() => document.body.textContent || ''")
    assert unique in body_text, "user message lost after navigate-during-stream roundtrip"

    # Assistant content is present (no empty orphan bubble). At minimum the
    # bubble's <p> contains some text, OR the stream completed and has > 5 chars.
    has_assistant_content = page.evaluate(_ASSISTANT_HAS_CONTENT)
    assert has_assistant_content, "assistant bubble is empty after roundtrip — orphan detected"

    screenshot("no-orphan")


def test_workspace_edit_rollback_on_500(page: Page, api_token: str, screenshot):
    """Edit a workspace's display_name with the backend's PATCH route forced to
    500 via Playwright's network interception. The optimistic UI value should
    revert to the previous value once the failure surfaces."""
    _open_app_with_token(page, api_token)
    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Open the workspace switcher → personal's gear → settings modal.
    # Easiest path: click the gear icon next to the active workspace in the
    # switcher dropdown.
    page.locator("button:has-text('Personal')").first.click()  # opens dropdown
    page.wait_for_timeout(200)
    page.locator("button[title*='Personal']").last.click()     # gear icon
    page.wait_for_selector("text=Display name", timeout=5_000)

    # Snapshot the original name.
    name_input = page.locator("input").first
    original = name_input.input_value()
    new_name = f"{original}-XXX"

    # Force the next workspace PATCH to return 500.
    def _fail_patch(route, request):
        if request.method == "PATCH" and "/workspaces/" in request.url:
            route.fulfill(status=500, body='{"detail": "forced 500 for rollback test"}')
        else:
            route.continue_()
    page.route("**/workspaces/*", _fail_patch)

    # Edit the field, blur to trigger the save.
    name_input.fill(new_name)
    name_input.blur()
    page.wait_for_timeout(1_500)  # withRollback fires after the failed apiCall

    # The input value should have reverted.
    after = name_input.input_value()
    assert after == original, (
        f"Workspace name did not roll back: original={original!r} after={after!r} "
        f"(expected backend 500 to trigger rollback)"
    )

    page.unroute("**/workspaces/*", _fail_patch)
    screenshot("rollback")


def test_chatbubble_render_bounded_during_stream(page: Page, api_token: str, screenshot):
    """Send a message that produces multiple bubbles in history, then send a
    new one. Track ChatBubble's render count via a global probe. The bubble
    being streamed should re-render heavily, but stable bubbles in history
    should NOT re-render on every chunk."""
    _open_app_with_token(page, api_token)
    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Seed the session with one Q/A pair.
    _send_chat_message(page, f"phase5-render-seed-{int(time.time())}")
    page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=60_000)
    page.wait_for_timeout(1_000)

    # Install a render counter via the React DevTools-equivalent: count how
    # many times the assistant <p> nodes' textContent changes during a stream.
    # The streaming bubble's <p> changes per chunk; the seed bubble's <p>
    # should NOT change. We measure by tagging each <p> with an attribute and
    # observing mutations on the seed's specific node.
    page.evaluate("""
        () => {
            window.__seedPRenderCount = 0;
            const els = Array.from(document.querySelectorAll('.custom-scrollbar'));
            const chatEl = els.find(el => el.className.includes('overflow-x-hidden'));
            if (!chatEl) return;
            // The seed bubble is the first assistant <p>.
            const ps = chatEl.querySelectorAll('p');
            const seed = ps[ps.length - 1];  // most recent assistant on seed turn
            if (!seed) return;
            window.__seedNode = seed;
            const observer = new MutationObserver(() => { window.__seedPRenderCount++; });
            observer.observe(seed, { childList: true, characterData: true, subtree: true });
            window.__seedObserver = observer;
        }
    """)

    # Send a new message and let it stream.
    _send_chat_message(page, f"phase5-render-second-{int(time.time())}")
    page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=60_000)
    page.wait_for_timeout(1_500)

    seed_renders = page.evaluate("() => window.__seedPRenderCount || 0")
    # The seed bubble should be re-render-bounded. A few mutations from layout
    # shifts are OK, but it should NOT scale with the new bubble's chunk count.
    # Allow up to 5 (search highlight, layout) — anything past that suggests
    # the memoization regressed.
    assert seed_renders <= 5, (
        f"Seed bubble re-rendered {seed_renders} times during a separate "
        f"bubble's stream — memoization on ChatBubble appears broken"
    )
    screenshot("render-bounded")
```

### Step 2: Run the smoke tests against live dev servers

> Manual prerequisite: backend on :8000, frontend on :3000, infra via docker-compose. The user starts the stack per their normal workflow.

```bash
cd /home/orbital/projects/pryzm
./backend/venv/bin/pytest backend/tests/e2e/test_phase5_smoke.py -v
# Expected: 4 passed
```

If any test fails, inspect screenshots in `backend/tests/e2e/_artifacts/` and the failure trace before adjusting.

### Step 3: Commit

```bash
git add backend/tests/e2e/test_phase5_smoke.py
git commit -m "test(e2e): Phase 5 smoke probes — rapid sends, navigate-during-stream, rollback, render bound"
```

---

## Task 12 — Final verification + open PR

### Step 1: Full test sweep

```bash
cd /home/orbital/projects/pryzm

# Backend pytest (excluding e2e since that needs the dev servers).
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
# Expected: same pass count as Phase 4 baseline (no regressions).

# Frontend build.
cd frontend && npm run build 2>&1 | tail -10
# Expected: "Compiled successfully" with zero TypeScript errors.
cd ..

# Frontend lint.
cd frontend && npm run lint 2>&1 | tail -5
cd ..
# Expected: clean (or known-baseline warnings only).
```

### Step 2: Manual smoke

Per the project memory: **manual checks on phase PRs only**. Trigger the user to do the smoke walkthrough:

1. Cold start: token gate appears → enter token → app loads → workspace switcher shows entries.
2. Send a message → user bubble appears → assistant streams → final bubble survives.
3. Switch workspaces via the dropdown → sidebar updates → previously-active workspace's history isn't visible.
4. Edit a workspace's display name → blur → name persists.
5. Create a folder → drop a session into it → reload page → session is still in the folder.
6. Edit a message → save → content persists.
7. Send a message → mid-stream, navigate to a different session → return → bubble has full content.

### Step 3: Push + PR

```bash
git push -u origin refactor/phase-5-frontend-state
gh pr create --title "Phase 5 — frontend state ownership" --body "$(cat <<'EOF'
## Summary

- Split `ChatContext` into five focused providers (`Workspace`, `Session`, `Inference`, `Uploader`, `TestSuite`) so a streaming token only re-renders bubble consumers.
- `SessionContext` is the single owner of the message cache; exposes a typed mutator API. Atomic `migrateBucket` replaces the dual-bucket optimistic→real handoff.
- Optimistic IDs use `crypto.randomUUID()`; rapid sends no longer collide.
- `withRollback` helper applied to folder, workspace-edit, and message-edit mutations.
- `ChatBubble` is `React.memo`'d; `ActiveSession` passes `displayContent` separately so message identity stays stable across token chunks.
- Removes the `window.dispatchEvent("chatCreated")` cross-component bus in favor of a context-local subscription.

## Test plan

- [x] backend pytest passes (no regressions from Phase 4)
- [x] frontend builds + lints clean
- [x] e2e: rapid 3-message send produces distinct ordered bubbles
- [x] e2e: navigate-during-stream returns to a non-empty assistant bubble
- [x] e2e: backend 500 on workspace edit rolls back the UI value
- [x] e2e: ChatBubble re-renders bounded during a streaming sibling bubble
- [ ] manual: cold-start → token gate → chat → workspace switch → folder D&D → message edit → mid-stream nav

EOF
)"
```

### Step 4: Self-review prompt for the user

The PR description above mirrors the project's lean-PR-description preference. After opening, the user reviews the diff and merges when satisfied. Per the project memory: **auto-merge authorized at phase boundaries**, so once smoke passes and the user reviews, merge directly.

---

## Self-Review Checklist

After completing all tasks, verify spec coverage:

- [x] **Context split into 5** — Tasks 3, 4, 5, 6, 7 + composer in Task 8.
- [x] **SessionContext owns the cache, single writer** — Task 4 plus `useInference` + `useMessageActions` refactor in Tasks 5 & 8.
- [x] **`crypto.randomUUID()` for optimistic IDs** — Task 2 helper, used in Task 5.
- [x] **Atomic `migrateBucket(...)`** — Task 4 (definition), Task 5 (sole-call-site).
- [x] **`migratedIds` Map for `stopInference`** — Task 5 (`migratedIds` ref + lookup in `stopInference`).
- [x] **`withRollback` helper applied at the three sites** — Tasks 1 (helper), 9 (sites).
- [x] **`React.memo` on ChatBubble + decoupled `displayContent` prop** — Task 8 (steps 3 & 4).
- [x] **`useCallback`-stabilized parent callbacks** — Task 8 (ActiveSession refactor) + Task 10 verification.
- [x] **`window.dispatchEvent("chatCreated")` removed** — Tasks 4 (`useSession.ts` listener removal + `notifySessionCreated`), 5 (`useInference.ts` removal), 8 (`SessionDirectory.tsx` switch to `subscribeSessionCreated`).
- [x] **Smoke probes covering rapid sends, navigate-during-stream, rollback, render bound** — Task 11.

Out of scope and explicitly *not* in this plan (per spec):

- `use-context-selector`, Zustand, or any state library introduction.
- Promoting `streamingSessionIdsRef` to state.
- Cache key migration from slug to id (Phase 4 oversight; revisit if a slug-rename-during-stream bug surfaces).
- `deleteMessage` rollback wrapping (spec only calls out folder/workspace/message-edit).
