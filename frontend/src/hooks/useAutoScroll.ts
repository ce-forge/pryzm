import { useState, useRef, useEffect, useCallback } from "react";

export function useAutoScroll(dependencies: any[]) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isAutoScrollEnabled, setIsAutoScrollEnabled] = useState(true);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current && isAutoScrollEnabled) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "auto",
      });
    }
  }, [isAutoScrollEnabled]);

  useEffect(() => {
    const timer = setTimeout(scrollToBottom, 30);
    return () => clearTimeout(timer);
  }, [dependencies, scrollToBottom]);

  const onScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;
    if (!isAtBottom && isAutoScrollEnabled) {
      setIsAutoScrollEnabled(false);
    } else if (isAtBottom && !isAutoScrollEnabled) {
      setIsAutoScrollEnabled(true);
    }
  };

  return { scrollRef, onScroll, setIsAutoScrollEnabled };
}