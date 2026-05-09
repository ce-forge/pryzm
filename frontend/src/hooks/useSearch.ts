import { useState, useEffect } from "react";

export function useSearch() {
  const [searchQuery, setSearchQuery] = useState("");
  const [totalMatches, setTotalMatches] = useState(0);
  const [searchIndex, setSearchIndex] = useState(0);
  const [isSearchOpen, setIsSearchOpen] = useState(false);

  useEffect(() => {
    setSearchIndex(0);
    if (searchQuery.trim()) {
      setTimeout(() => {
        const marks = document.querySelectorAll('.search-match');
        if (marks[0]) marks[0].scrollIntoView({ behavior: "smooth", block: "center" });
      }, 50);
    }
  }, [searchQuery]);

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
    searchQuery, setSearchQuery,
    totalMatches, setTotalMatches,
    searchIndex, setSearchIndex,
    isSearchOpen, setIsSearchOpen,
    scrollToMatch
  };
}