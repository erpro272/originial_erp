import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge must know our custom colour tokens, otherwise e.g. `text-md` (amber
 * colour) is mistaken for a font-size and silently dropped next to `text-xs`.
 * Keep this list in sync with the colour tokens in styles.css.
 */
const COLORS = [
  "primary",
  "primary-hover",
  "link",
  "link-hover",
  "ink",
  "ink-2",
  "ink-3",
  "muted",
  "subtle",
  "faint",
  "line",
  "line-input",
  "divider",
  "divider-2",
  "surface",
  "surface-2",
  "surface-blue",
  "in",
  "in-bg",
  "in-line",
  "te",
  "te-bg",
  "te-line",
  "load",
  "s1",
  "s2",
  "s3",
  "s4",
  "s5",
  "load-ink",
  "hi",
  "hi-bg",
  "hi-line",
  "hi-wash",
  "md",
  "md-bg",
  "md-line",
  "md-accent",
  "lo",
  "lo-bg",
  "ok",
  "ok-bg",
  "ok-line",
  "bl",
  "bl-bg",
  "bl-line",
  "ai",
  "ai-bg",
  "ai-wash",
  "ai-line",
];

const twMerge = extendTailwindMerge({
  extend: { theme: { color: COLORS, radius: ["chip", "bar", "tip", "card", "modal"] } },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
