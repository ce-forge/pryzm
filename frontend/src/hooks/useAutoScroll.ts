import { useRef, useEffect, useCallback } from "react";

interface UseAutoScrollArgs {
  /** Tracked only to force-enable scrolling when a new message lands —
   *  e.g. the user just hit send, or restored after a scroll-up. */
  messages: { id?: string }[];
}

/**
 * Auto-scroll for the chat feed.
 *
 * Approach: a zero-height sentinel `<div ref={bottomRef}>` at the bottom
 * of the content, plus a `MutationObserver` on the scroll container's
 * entire subtree. Any DOM change anywhere — token-by-token text growth
 * inside a streaming bubble, ThinkingPanel expanding/collapsing, Prism
 * syntax highlighting committing, image loads — fires the observer and
 * schedules a `bottomRef.scrollIntoView({block: "end"})` call (rAF-gated
 * so a burst from one render coalesces into one scroll).
 *
 * MutationObserver fires on text-node mutations directly, which is more
 * reliable than ResizeObserver during streaming — the bubble's measured
 * size sometimes hasn't committed by the time the resize event would
 * fire, but the text node mutation always has.
 *
 * User scroll-up disables autoscroll immediately via velocity detection
 * (scrollTop decreased between events); scrolling back to within 30 px
 * of the bottom re-enables.
 */
export function useAutoScroll({ messages }: UseAutoScrollArgs) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const isAutoScrollEnabled = useRef(true);
  const lastScrollTop = useRef<number | null>(null);

  const scrollToBottom = useCallback((force = false) => {
    const sentinel = bottomRef.current;
    if (!sentinel) return;
    if (!force && !isAutoScrollEnabled.current) return;
    if (force) isAutoScrollEnabled.current = true;
    sentinel.scrollIntoView({ behavior: "auto", block: "end" });
  }, []);

  // Force a scroll when a new message lands — covers the user just
  // hitting send and restores autoscroll if they'd scrolled up before.
  useEffect(() => {
    const t = setTimeout(() => scrollToBottom(true), 30);
    return () => clearTimeout(t);
  }, [messages.length, scrollToBottom]);

  // Primary trigger — any DOM mutation inside the scroll container.
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;

    let frameScheduled = false;
    const trigger = () => {
      if (frameScheduled) return;
      frameScheduled = true;
      requestAnimationFrame(() => {
        frameScheduled = false;
        scrollToBottom();
      });
    };

    const obs = new MutationObserver(trigger);
    obs.observe(sc, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => obs.disconnect();
  }, [scrollToBottom]);

  const onScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    const userScrolledUp =
      lastScrollTop.current !== null && scrollTop < lastScrollTop.current;
    if (userScrolledUp) {
      isAutoScrollEnabled.current = false;
    } else if (distanceFromBottom < 30) {
      isAutoScrollEnabled.current = true;
    }
    lastScrollTop.current = scrollTop;
  };

  return { scrollRef, bottomRef, onScroll, scrollToBottom };
}
