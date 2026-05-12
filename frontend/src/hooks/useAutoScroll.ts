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

  const onScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 250;
    if (!isAtBottom && isAutoScrollEnabled.current) {
      isAutoScrollEnabled.current = false;
    } else if (isAtBottom && !isAutoScrollEnabled.current) {
      isAutoScrollEnabled.current = true;
    }
  };

  return { scrollRef, onScroll, scrollToBottom };
}