import { useRef, useEffect, useCallback } from "react";

interface UseAutoScrollArgs {
  /** Tracked only to force-enable scrolling when a new message lands —
   *  e.g. the user just hit send, or restored after a scroll-up. */
  messages: { id?: string }[];
}

/**
 * Auto-scroll for the chat feed.
 *
 * Approach:
 *   - A `MutationObserver` on the scroll container's entire subtree.
 *     Any DOM change anywhere — token-by-token text growth inside a
 *     streaming bubble, ThinkingPanel expanding/collapsing, markdown
 *     reflow, image loads — fires the observer and (when autoscroll is
 *     enabled) sets `scrollTop = scrollHeight` so the latest bottom is
 *     in view. The observer fires once inline AND once in the next
 *     animation frame, the second catching content that committed
 *     between the mutation and the next paint.
 *   - Wheel + touchmove listeners flip autoscroll OFF the moment the
 *     user moves up. These fire BEFORE the next mutation, which is
 *     critical: the scroll event (the only signal `onScroll` has) fires
 *     asynchronously, and during streaming the next mutation can pull
 *     the position back to bottom before `onScroll` ever runs.
 *   - `onScroll` provides a fallback re-engage: scrolling down into the
 *     bottom 150 px zone, or being within 5 px of the absolute bottom,
 *     turns autoscroll back on.
 */
export function useAutoScroll({ messages }: UseAutoScrollArgs) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const isAutoScrollEnabled = useRef(true);
  const lastScrollTop = useRef<number | null>(null);

  const scrollToBottom = useCallback((force = false) => {
    const sc = scrollRef.current;
    if (!sc) return;
    if (!force && !isAutoScrollEnabled.current) return;
    if (force) isAutoScrollEnabled.current = true;
    // Read scrollHeight at call time so we always target the latest
    // bottom. Setting scrollTop is idempotent — the browser doesn't
    // re-paint if the value is unchanged.
    sc.scrollTop = sc.scrollHeight;
  }, []);

  // Force a scroll when a new message lands — covers the user just
  // hitting send and restores autoscroll if they'd scrolled up before.
  useEffect(() => {
    const t = setTimeout(() => scrollToBottom(true), 30);
    return () => clearTimeout(t);
  }, [messages.length, scrollToBottom]);

  // Primary trigger — any DOM mutation inside the scroll container.
  // Fires inline AND in the next frame: inline grabs the current
  // scrollHeight, the rAF chases any additional content that committed
  // before the next paint.
  //
  // The rAF callback is wrapped in `() => scrollToBottom()` rather than
  // passing `scrollToBottom` directly — `requestAnimationFrame` invokes
  // its callback with a DOMHighResTimeStamp as the first argument, and
  // since `scrollToBottom`'s `force` arg accepts any truthy value, a
  // bare reference here would force-scroll every frame, re-enabling
  // autoscroll after the user disabled it via wheel.
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;

    const obs = new MutationObserver(() => {
      scrollToBottom();
      requestAnimationFrame(() => scrollToBottom());
    });
    obs.observe(sc, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => obs.disconnect();
  }, [scrollToBottom]);

  // User-intent listeners — wheel + touch fire BEFORE the browser's
  // scroll event, and BEFORE the next mutation can pull the position
  // back to bottom. Without these the race is unwinnable.
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;

    let touchStartY: number | null = null;

    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < 0) isAutoScrollEnabled.current = false;
    };
    const onTouchStart = (e: TouchEvent) => {
      touchStartY = e.touches[0]?.clientY ?? null;
    };
    const onTouchMove = (e: TouchEvent) => {
      const y = e.touches[0]?.clientY;
      if (y == null || touchStartY == null) return;
      // Finger moving DOWN (clientY increasing) = page scrolls UP.
      if (y > touchStartY + 4) isAutoScrollEnabled.current = false;
      touchStartY = y;
    };

    sc.addEventListener("wheel", onWheel, { passive: true });
    sc.addEventListener("touchstart", onTouchStart, { passive: true });
    sc.addEventListener("touchmove", onTouchMove, { passive: true });
    return () => {
      sc.removeEventListener("wheel", onWheel);
      sc.removeEventListener("touchstart", onTouchStart);
      sc.removeEventListener("touchmove", onTouchMove);
    };
  }, []);

  const onScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    const last = lastScrollTop.current;
    const scrolledUp = last !== null && scrollTop < last;
    const scrolledDown = last !== null && scrollTop > last;
    if (scrolledUp) {
      isAutoScrollEnabled.current = false;
    }
    if ((scrolledDown && distanceFromBottom < 150) || distanceFromBottom < 5) {
      isAutoScrollEnabled.current = true;
    }
    lastScrollTop.current = scrollTop;
  };

  return { scrollRef, bottomRef, onScroll, scrollToBottom };
}
