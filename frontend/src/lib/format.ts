/**
 * Formatting helpers. Money is always integer paise from the API (never floats).
 */
const IN = "en-IN";

/** 5000000_00 paise -> "50,00,000" (rupees, Indian grouping, no decimals). */
export function rupees(paise: number, opts: { decimals?: boolean } = {}): string {
  const r = paise / 100;
  return r.toLocaleString(IN, {
    minimumFractionDigits: opts.decimals ? 2 : 0,
    maximumFractionDigits: opts.decimals ? 2 : 0,
  });
}

/** Compact Indian notation used on cards and KPIs: "₹50.0 L", "₹1.2 Cr", "₹18,400". */
export function rupeesCompact(paise: number): string {
  const r = paise / 100;
  const abs = Math.abs(r);
  const sign = r < 0 ? "−" : "";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(1)} L`;
  return `${sign}₹${abs.toLocaleString(IN, { maximumFractionDigits: 0 })}`;
}

/** 120000 -> "1,20,000" */
export function count(n: number): string {
  return n.toLocaleString(IN);
}

export function percent(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** "Mon 16 Nov" (mockup style). */
export function shortDate(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

/** "13 Nov 2026, 19:24" */
export function dateTime(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}
