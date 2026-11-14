import { useState } from "react";
import { rupees, rupeesCompact } from "@/lib/format";

interface Point {
  month: string; // ISO date, first of month
  sales_paise: number;
}

const W = 560;
const H = 180;
const PAD = { top: 12, right: 8, bottom: 26, left: 52 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(v));
  const f = v / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * exp;
}

const monthLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { month: "short" });
const monthLong = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });

/**
 * Single-series column chart: one hue (primary, validated against the surface), columns
 * capped at 24px with 4px rounded tops on a square baseline, hairline grid, per-column
 * hover/focus tooltip, and a visually hidden table for screen readers.
 */
export function MonthlySalesChart({ data, months }: { data: Point[]; months: string[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const byMonth = new Map(data.map((d) => [d.month, d.sales_paise]));
  const series = months.map((m) => ({ month: m, value: byMonth.get(m) ?? 0 }));
  const max = niceMax(Math.max(...series.map((s) => s.value), 0));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const band = innerW / series.length;
  const barW = Math.min(24, band - 6);
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const ticks = [0, max / 2, max];

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block h-auto w-full"
        role="img"
        aria-label="Monthly sales, last 12 months"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--color-divider)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(t)}
              dy="0.32em"
              textAnchor="end"
              fontSize="11"
              fill="var(--color-muted)"
            >
              {t === 0 ? "0" : rupeesCompact(t)}
            </text>
          </g>
        ))}
        {series.map((s, i) => {
          const x = PAD.left + i * band + (band - barW) / 2;
          const top = y(s.value);
          const hgt = PAD.top + innerH - top;
          const r = Math.min(4, hgt);
          return (
            <g
              key={s.month}
              tabIndex={0}
              role="img"
              aria-label={`${monthLong(s.month)}: ₹${rupees(s.value)}`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              className="outline-none"
            >
              {/* hit target: the whole column band, bigger than the mark */}
              <rect
                x={PAD.left + i * band}
                y={PAD.top}
                width={band}
                height={innerH}
                fill="transparent"
              />
              {s.value > 0 && (
                <path
                  d={`M${x},${PAD.top + innerH} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${PAD.top + innerH} Z`}
                  fill="var(--color-primary)"
                  opacity={hover === null || hover === i ? 1 : 0.45}
                />
              )}
              <text
                x={x + barW / 2}
                y={H - 8}
                textAnchor="middle"
                fontSize="11"
                fill="var(--color-muted)"
              >
                {monthLabel(s.month)}
              </text>
            </g>
          );
        })}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={PAD.top + innerH}
          y2={PAD.top + innerH}
          stroke="var(--color-line)"
        />
        {hover !== null && (
          <g pointerEvents="none">
            {(() => {
              const s = series[hover]!;
              const cx = Math.min(
                Math.max(PAD.left + hover * band + band / 2, PAD.left + 70),
                W - 70,
              );
              return (
                <>
                  <rect
                    x={cx - 66}
                    y={2}
                    width={132}
                    height={36}
                    rx={8}
                    fill="white"
                    stroke="var(--color-line)"
                  />
                  <text x={cx} y={16} textAnchor="middle" fontSize="11" fill="var(--color-muted)">
                    {monthLong(s.month)}
                  </text>
                  <text
                    x={cx}
                    y={31}
                    textAnchor="middle"
                    fontSize="12"
                    fontWeight="600"
                    fill="var(--color-ink)"
                  >
                    ₹{rupees(s.value)}
                  </text>
                </>
              );
            })()}
          </g>
        )}
      </svg>
      <table className="sr-only">
        <caption>Monthly sales</caption>
        <thead>
          <tr>
            <th>Month</th>
            <th>Sales (₹)</th>
          </tr>
        </thead>
        <tbody>
          {series.map((s) => (
            <tr key={s.month}>
              <td>{monthLong(s.month)}</td>
              <td>{rupees(s.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

/** The last 12 calendar months (ISO first-of-month), oldest first. */
export function last12Months(today = new Date()): string[] {
  const out: string[] = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`);
  }
  return out;
}
