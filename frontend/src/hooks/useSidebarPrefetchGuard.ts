// Module-level mutable state — intentionally not React state so it is zero-cost
// to read inside event handlers and does not trigger any re-renders.
let isScrolling = false;
let timer: number | null = null;

/** Call this from the sidebar scroll container's onScroll handler. */
export function markSidebarScrolling() {
  isScrolling = true;
  if (timer !== null) window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    isScrolling = false;
    timer = null;
  }, 200);
}

/** Returns true while the sidebar is actively scrolling (within 200ms of last scroll event). */
export function isSidebarScrolling(): boolean {
  return isScrolling;
}
