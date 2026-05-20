export const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  open: { bg: "bg-amber-500/15", text: "text-amber-300" },
  acknowledged: { bg: "bg-sky-500/15", text: "text-sky-300" },
  resolved: { bg: "bg-emerald-500/15", text: "text-emerald-300" },
  dismissed: { bg: "bg-gray-500/15", text: "text-gray-400" },
};

export function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] ?? {
    bg: "bg-gray-500/15",
    text: "text-gray-300",
  };
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${c.bg} ${c.text}`}
    >
      {status}
    </span>
  );
}
