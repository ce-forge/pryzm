import { useRef, useEffect, useCallback } from "react";

interface UseAutoScrollArgs {
  /** Tracked only to force-enable scrolling when a new message lands —
   *  e.g. the user just hit send, or restored after a scroll-up. */
  messages: { id?: string }[];
  /** The live streaming content/reasoning text. ResizeObserver is the
   *  primary trigger, but Markdown layout sometimes commits a frame
   *  AFTER the state update lands — watching the text directly as a
   *  belt-and-suspenders trigger guarantees a scroll on every chunk. */
  streamingText?: string;
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
export function useAutoScroll({ messages, streamingText }: UseAutoScrollArgs) {
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

  // (2) Primary scroll trigger — observe everything inside the scroll
  // container. Anything that grows the page (token stream, pill expand,
  // markdown reflow) fires the observer; if autoscroll is enabled, follow.
  // rAF gate coalesces a burst of size changes from one render into one
  // scroll call.
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;
    const content = sc.firstElementChild as Element | null;
    if (!content) return;

    let frameScheduled = false;
    const trigger = () => {
      if (frameScheduled) return;
      frameScheduled = true;
      requestAnimationFrame(() => {
        frameScheduled = false;
        scrollToBottom();
      });
    };
    const observer = new ResizeObserver(trigger);
    observer.observe(content);
    // Also observe individual message bubbles as they arrive — when a
    // bubble's height changes (markdown reflow inside a code block, image
    // load), its own resize fires before/in addition to the parent's.
    const mutation = new MutationObserver(() => {
      observer.disconnect();
      observer.observe(content);
      Array.from(content.children).forEach((c) => observer.observe(c));
      trigger();
    });
    mutation.observe(content, { childList: true, subtree: false });
    Array.from(content.children).forEach((c) => observer.observe(c));

    return () => {
      observer.disconnect();
      mutation.disconnect();
    };
  }, [scrollToBottom]);

  // (3) Backup trigger — every streamingText state change. Markdown
  // layout occasionally commits a frame later than the state update;
  // this guarantees a scroll attempt the moment a token lands.
  useEffect(() => {
    if (!streamingText) return;
    requestAnimationFrame(() => scrollToBottom());
  }, [streamingText, scrollToBottom]);

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
