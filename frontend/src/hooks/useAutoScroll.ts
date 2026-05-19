import { useRef, useEffect, useCallback } from "react";

interface UseAutoScrollArgs {
  /** Length tracked: scroll forced when a new message lands. */
  messages: { id?: string }[];
  /** Latest streaming chunk content (or empty string). Drives soft scroll
   * while the model is mid-response. */
  streamingText: string;
  /** True while a stream is in flight. */
  isProcessing: boolean;
}

/**
 * Owns BOTH halves of chat auto-scroll:
 *   1. Hard scroll-to-bottom when the user sends or the session changes (new
 *      message lands → messages.length grows).
 *   2. Soft scroll-to-bottom while the assistant is mid-stream (streamingText
 *      grows but the array length doesn't).
 * Caller renders the returned scrollRef on the scrolling div and the onScroll
 * handler. No additional scroll effects should live in the caller.
 */
export function useAutoScroll({ messages, streamingText, isProcessing }: UseAutoScrollArgs) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Ref (not state) so user-driven scroll-up doesn't trigger a re-render
  // loop. When the user scrolls away from the bottom we disable auto-scroll
  // until they return.
  const isAutoScrollEnabled = useRef(true);
  // Tracks the last observed scrollTop so we can tell whether the latest
  // scroll event was the user moving up (scrollTop decreased) vs. our own
  // programmatic scrollTo at the end of a chunk (scrollTop increased).
  // Null on first call — we wait one event to establish the baseline.
  const lastScrollTop = useRef<number | null>(null);

  const scrollToBottom = useCallback((force = false) => {
    if (scrollRef.current && (isAutoScrollEnabled.current || force)) {
      if (force) isAutoScrollEnabled.current = true;
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "auto",
      });
    }
  }, []);

  // (1) New message arrived — force scroll regardless of user's scroll state.
  useEffect(() => {
    const timer = setTimeout(() => scrollToBottom(true), 30);
    return () => clearTimeout(timer);
  }, [messages.length, scrollToBottom]);

  // (2) Streaming-content updates: only auto-scroll while the user hasn't
  // scrolled away. Settling pass after the stream ends to catch the final
  // layout shift once tokens stop arriving.
  useEffect(() => {
    if (isProcessing && streamingText) {
      scrollToBottom();
    } else if (!isProcessing) {
      const timer = setTimeout(() => scrollToBottom(), 50);
      return () => clearTimeout(timer);
    }
  }, [streamingText, isProcessing, scrollToBottom]);

  // Disable as soon as the user scrolls up by ANY amount — the previous
  // position-threshold-only check let small wheel/touch movements get
  // swallowed by the next chunk's programmatic scrollTo, which felt like
  // the page was fighting the user. Re-enable only when they're back at
  // the very bottom (tight 30px threshold).
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