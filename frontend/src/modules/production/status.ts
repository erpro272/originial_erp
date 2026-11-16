import type { StationStatus } from "./demoData";

/** Status colours for the factory layout legend, hover card and Status view. */
export const STATUS: Record<
  StationStatus,
  { label: string; dot: string; tag: string; tint: string }
> = {
  running: { label: "Running", dot: "bg-ok", tag: "bg-ok-bg text-ok", tint: "border-ok bg-ok-bg" },
  idle: { label: "Idle", dot: "bg-primary", tag: "bg-bl-bg text-bl", tint: "border-bl bg-bl-bg" },
  maintenance: {
    label: "Maintenance",
    dot: "bg-md-accent",
    tag: "bg-md-bg text-md",
    tint: "border-md-accent bg-md-bg",
  },
  issue: { label: "Issue", dot: "bg-hi", tag: "bg-hi-bg text-hi", tint: "border-hi bg-hi-bg" },
};
