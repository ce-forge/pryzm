"use client";

export const TEMPLATE_COLORS = [
  "blue",
  "orange",
  "emerald",
  "red",
  "amber",
  "violet",
  "cyan",
  "pink",
  "white",
];

export function ColorPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      <button
        type="button"
        onClick={() => onChange(null)}
        className={
          "text-xs px-2 py-1 rounded border " +
          (value === null
            ? "bg-[#2a2a2c] border-[#3a3a3c] text-[#e3e3e3]"
            : "border-[#2a2a2c] text-gray-400")
        }
      >
        none
      </button>
      {TEMPLATE_COLORS.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={
            "text-xs px-2 py-1 rounded border " +
            (value === c
              ? "bg-[#2a2a2c] border-[#3a3a3c] text-[#e3e3e3]"
              : "border-[#2a2a2c] text-gray-400 hover:text-[#e3e3e3]")
          }
        >
          {c}
        </button>
      ))}
    </div>
  );
}
