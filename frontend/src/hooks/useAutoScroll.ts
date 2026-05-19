import { useRef, useEffect, useCallback } from "react";

interface UseAutoScrollArgs {
  /** Tracked only to force-enable scrolling when a new message lands —
   *  e.g. the user just hit send, or restored after a scroll-up. */
  messages: { id?: string }[];
}

/**
 * Auto-scroll for the chat feed. Uses a `ResizeObserver` on the content
 * container instead of watching streaming-text state, so it catches every
 * thing that changes the page height — token streams, ThinkingPanel
 * expanding/collapsing, Prism syntax highlighting reflowing code blocks,
 * referenced-file previews loading — without coupling the scroll hook to
 * any specific state source. User scroll-up disables autoscroll
 * immediately; scrolling back to within 30 px of the bottom re-enables.
 */
export function useAutoScroll({ messages }: UseAutoScrollArgs) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Ref (not state) so user-driven scroll-up doesn't trigger a render loop.
  const isAutoScrollEnabled = useRef(true);
  // Velocity detector. Programmatic scrollTo always *increases* scrollTop;
  // a decrease means the user moved up. Null on first call — wait one
  // event to establish the baseline so the initial scroll doesn't trip it.
  const lastScrollTop = useRef<number | null>(null);

  const scrollToBottom = useCallback((force = false) => {
    const sc = scrollRef.current;
    if (!sc) return;
    if (!force && !isAutoScrollEnabled.current) return;
    if (force) isAutoScrollEnabled.current = true;
    sc.scrollTo({ top: sc.scrollHeight, behavior: "auto" });
  }, []);

  // (1) Force a scroll when a new message lands. Covers the user just
  // hitting send, and restores autoscroll if they'd scrolled up before.
  useEffect(() => {
    const t = setTimeout(() => scrollToBottom(true), 30);
    return () => clearTimeout(t);
  }, [messages.length, scrollToBottom]);

  // (2) The actual scroll trigger. Anything that grows the page (token
  // stream, pill expand, markdown reflow) fires the observer; if
  // autoscroll is enabled, follow. rAF gate coalesces a burst of size
  // changes from one render into a single scroll call.
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;
    const content = sc.firstElementChild as Element | null;
    if (!content) return;

    let frameScheduled = false;
    const observer = new ResizeObserver(() => {
      if (frameScheduled) return;
      frameScheduled = true;
      requestAnimationFrame(() => {
        frameScheduled = false;
        scrollToBottom();
      });
    });
    observer.observe(content);
    return () => observer.disconnect();
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

  return { scrollRef, onScroll, scrollToBottom };
}
