"use client";

import { ReactNode, useEffect } from "react";

export function ModalShell({
  title,
  onClose,
  children,
  size = "max-w-md",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  size?: string;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className={`bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full ${size} max-h-[85vh] overflow-hidden flex flex-col border border-[#2a2a2c]`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="overflow-y-auto custom-scrollbar">{children}</div>
      </div>
    </div>
  );
}
