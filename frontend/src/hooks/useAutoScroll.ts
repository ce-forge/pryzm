import { useRef, useEffect, useCallback } from "react";

export function useAutoScroll(dependencies: any[]) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // FIX: Using a ref instead of state prevents an infinite dependency loop 
  // that was locking the user's ability to scroll manually.
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

  useEffect(() => {
    const timer = setTimeout(() => scrollToBottom(true), 30);
    return () => clearTimeout(timer);
  }, [dependencies?.length, scrollToBottom]);

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