/** Soft card / icon / line tones of the Clean Kri KPI cards (Production, Dashboard). */
export type Tone = "ok" | "bl" | "ai" | "hi" | "md";

export const TONE: Record<Tone, { stroke: string; icon: string; card: string; text: string }> = {
  ok: {
    stroke: "stroke-ok",
    icon: "bg-ok-bg text-ok",
    card: "bg-ok-bg/40 border-ok-line/60",
    text: "text-ok",
  },
  bl: {
    stroke: "stroke-primary",
    icon: "bg-bl-bg text-primary",
    card: "bg-bl-bg/40 border-bl-line/60",
    text: "text-bl",
  },
  ai: {
    stroke: "stroke-ai",
    icon: "bg-ai-bg text-ai",
    card: "bg-ai-bg/40 border-ai-line",
    text: "text-ai",
  },
  hi: {
    stroke: "stroke-hi",
    icon: "bg-hi-bg text-hi",
    card: "bg-hi-bg/40 border-hi-line/60",
    text: "text-hi",
  },
  md: {
    stroke: "stroke-md-accent",
    icon: "bg-md-bg text-md",
    card: "bg-md-bg/40 border-md-line/60",
    text: "text-md",
  },
};
