interface Props {
  eventType: string;
}

const PREFIX_COLORS: Record<string, { bg: string; text: string }> = {
  auth: { bg: "bg-red-500/15", text: "text-red-300" },
  admin: { bg: "bg-violet-500/15", text: "text-violet-300" },
  chat: { bg: "bg-sky-500/15", text: "text-sky-300" },
  workspace: { bg: "bg-emerald-500/15", text: "text-emerald-300" },
  folder: { bg: "bg-cyan-500/15", text: "text-cyan-300" },
  document: { bg: "bg-orange-500/15", text: "text-orange-300" },
  bugreport: { bg: "bg-amber-500/15", text: "text-amber-300" },
  notification: { bg: "bg-pink-500/15", text: "text-pink-300" },
};

const FALLBACK = { bg: "bg-gray-500/15", text: "text-gray-300" };

export function EventTypeBadge({ eventType }: Props) {
  const [prefix, ...rest] = eventType.split(".");
  const colors = PREFIX_COLORS[prefix] ?? FALLBACK;
  const suffix = rest.join(".");
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${colors.bg} ${colors.text}`}
      >
        {prefix}
      </span>
      <span className="font-mono text-xs text-[#e3e3e3]">{suffix}</span>
    </span>
  );
}
