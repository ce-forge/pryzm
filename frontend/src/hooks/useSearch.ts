import { useState, useEffect } from "react";

export function useSearch(messages: any[]) { // Add messages as dependency
  const [searchQuery, setSearchQuery] = useState("");
  const [totalMatches, setTotalMatches] = useState(0);
  const [searchIndex, setSearchIndex] = useState(0);
  const [isSearchOpen, setIsSearchOpen] = useState(false);

  // Synchronize matches with the DOM
  useEffect(() => {
    if (!searchQuery) {
      setTotalMatches(0);
      return;
    }

    const timer = setTimeout(() => {
      const marks = document.querySelectorAll('.search-match');
      setTotalMatches(marks.length);

      marks.forEach((mark, i) => {
        const element = mark as HTMLElement;
        if (i === searchIndex) {
          element.style.backgroundColor = '#3b82f6';
          element.style.color = '#ffffff';
          element.classList.add('shadow-sm', 'shadow-blue-900/50', 'z-10');
        } else {
          element.style.backgroundColor = 'rgba(59, 130, 246, 0.2)';
          element.style.color = '#93c5fd';
          element.classList.remove('shadow-sm', 'shadow-blue-900/50', 'z-10');
        }
      });
    }, 50);

    return () => clearTimeout(timer);
  }, [searchQuery, searchIndex, messages]);

  const scrollToMatch = (index: number) => {
    if (totalMatches === 0) return;
    const safeIndex = (index + totalMatches) % totalMatches;
    setSearchIndex(safeIndex);

    setTimeout(() => {
      const marks = document.querySelectorAll('.search-match');
      if (marks[safeIndex]) marks[safeIndex].scrollIntoView({ behavior: "smooth", block: "center" });
    }, 10);
  };

  return {
    searchQuery, setSearchQuery, totalMatches, searchIndex, 
    isSearchOpen, setIsSearchOpen, scrollToMatch
  };
}