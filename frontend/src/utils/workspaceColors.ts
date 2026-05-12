export const WORKSPACE_COLORS = {
  blue:    { dot: "bg-blue-500",    badge: "bg-blue-500/10 text-blue-400 border-blue-500/20",          ring: "ring-blue-500",    text: "text-blue-400" },
  orange:  { dot: "bg-orange-500",  badge: "bg-orange-500/10 text-orange-400 border-orange-500/20",    ring: "ring-orange-500",  text: "text-orange-400" },
  emerald: { dot: "bg-emerald-500", badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", ring: "ring-emerald-500", text: "text-emerald-400" },
  red:     { dot: "bg-red-500",     badge: "bg-red-500/10 text-red-400 border-red-500/20",             ring: "ring-red-500",     text: "text-red-400" },
  amber:   { dot: "bg-amber-500",   badge: "bg-amber-500/10 text-amber-400 border-amber-500/20",       ring: "ring-amber-500",   text: "text-amber-400" },
  violet:  { dot: "bg-violet-500",  badge: "bg-violet-500/10 text-violet-400 border-violet-500/20",    ring: "ring-violet-500",  text: "text-violet-400" },
  cyan:    { dot: "bg-cyan-500",    badge: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",          ring: "ring-cyan-500",    text: "text-cyan-400" },
  pink:    { dot: "bg-pink-500",    badge: "bg-pink-500/10 text-pink-400 border-pink-500/20",          ring: "ring-pink-500",    text: "text-pink-400" },
  white:   { dot: "bg-white",      badge: "bg-white/10 text-white border-white/20",                    ring: "ring-white",       text: "text-white" },
} as const;

export type WorkspaceColor = keyof typeof WORKSPACE_COLORS;
export const WORKSPACE_COLOR_NAMES = Object.keys(WORKSPACE_COLORS) as WorkspaceColor[];
export const DEFAULT_WORKSPACE_COLOR: WorkspaceColor = "blue";

export function getWorkspaceColorClasses(color: string | null | undefined) {
  if (color && color in WORKSPACE_COLORS) {
    return WORKSPACE_COLORS[color as WorkspaceColor];
  }
  return WORKSPACE_COLORS[DEFAULT_WORKSPACE_COLOR];
}
