import { useState } from "react";
import { cn } from "@/lib/cn";
import { rupeesCompact } from "@/lib/format";
import type { CashMonth } from "./api";

const W = 560;
const H = 220;
const PAD = { l: 56, r: 12, t: 12, b: 28 };

const SERIES = [
  { key: "invoiced", label: "Invoiced", fill: "fill-s1", dot: "bg-s1" },
  { key: "collected", label: "Collected", fill: "fill-s3", dot: "bg-s3" },
] as const;

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

/** Invoiced vs Collected (bars) and Payables (line), last 6 months. Hover a month for the numbers. */
export function CashFlowChart({ months }: { months: CashMonth[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = niceMax(Math.max(1, ...months.flatMap((m) => [m.invoiced, m.collected, m.payables])));
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;
  const step = iw / months.length;
  const y = (v: number) => PAD.t + ih - (v / max) * ih;
  const bw = Math.min(26, step * 0.28);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const line = months.map((m, i) => `${PAD.l + step * (i + 0.5)},${y(m.payables)}`).join(" ");
  const h = hover != null ? months[hover] : null;

  return (
    <div className="flex flex-col gap-3">
      <ul className="m-0 flex list-none flex-wrap gap-4 p-0 text-[12px] text-ink-3">
        {SERIES.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span className={cn("size-2.5 rounded-sm", s.dot)} />
            {s.label}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded bg-s4" />
          Payables (supplier bills)
        </li>
      </ul>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label="Cash flow, last 6 months"
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="stroke-divider" />
              <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" className="fill-muted text-[11px]">
                {rupeesCompact(t)}
              </text>
            </g>
          ))}
          {months.map((m, i) => {
            const cx = PAD.l + step * (i + 0.5);
            return (
              <g key={m.month} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect
                  x={cx - step / 2}
                  y={PAD.t}
                  width={step}
                  height={ih}
                  className={cn("fill-transparent", hover === i && "fill-surface")}
                />
                <rect
                  x={cx - bw - 2}
                  y={y(m.invoiced)}
                  width={bw}
                  height={PAD.t + ih - y(m.invoiced)}
                  rx="3"
                  className="fill-s1"
                />
                <rect
                  x={cx + 2}
                  y={y(m.collected)}
                  width={bw}
                  height={PAD.t + ih - y(m.collected)}
                  rx="3"
                  className="fill-s3"
                />
                <text x={cx} y={H - 8} textAnchor="middle" className="fill-ink-3 text-[12px]">
                  {m.label}
                </text>
              </g>
            );
          })}
          <polyline
            points={line}
            fill="none"
            className="pointer-events-none stroke-s4"
            strokeWidth="2"
          />
          {months.map((m, i) => (
            <circle
              key={m.month}
              cx={PAD.l + step * (i + 0.5)}
              cy={y(m.payables)}
              r="3.5"
              className="pointer-events-none fill-white stroke-s4"
              strokeWidth="2"
            />
          ))}
        </svg>
        {h && hover != null && (
          <div
            role="status"
            className="pointer-events-none absolute top-2 z-10 w-[210px] rounded-tip border border-line bg-white px-3.5 py-2.5 text-[12px] shadow-tip"
            style={{
              left: `${Math.min(70, Math.max(0, ((PAD.l + step * (hover + 0.5)) / W) * 100 - 18))}%`,
            }}
          >
            <div className="mb-1 font-semibold text-ink">{h.label}</div>
            {(
              [
                ["Invoiced", h.invoiced],
                ["Collected", h.collected],
                ["Payables (bills received)", h.payables],
                ["Paid to suppliers", h.paid],
              ] as const
            ).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3">
                <span className="text-muted">{k}</span>
                <span className="font-medium text-ink">{rupeesCompact(v)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <table className="sr-only">
        <caption>Cash flow by month</caption>
        <thead>
          <tr>
            <th>Month</th>
            <th>Invoiced</th>
            <th>Collected</th>
            <th>Payables</th>
            <th>Paid to suppliers</th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={m.month}>
              <td>{m.label}</td>
              <td>{rupeesCompact(m.invoiced)}</td>
              <td>{rupeesCompact(m.collected)}</td>
              <td>{rupeesCompact(m.payables)}</td>
              <td>{rupeesCompact(m.paid)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
