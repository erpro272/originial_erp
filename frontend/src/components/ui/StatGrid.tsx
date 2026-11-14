import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Skeleton } from "./Skeleton";
import type { KpiTone } from "./KpiStrip";

const tone: Record<KpiTone, string> = {
  ink: "text-ink",
  hi: "text-hi",
  bl: "text-bl",
  md: "text-md",
  ok: "text-ok",
};

export interface Stat {
  label: string;
  value: ReactNode;
  caption?: ReactNode;
  tone?: KpiTone;
}

/** Metrics box from the updated mockup: equal cells in one bordered surface box. */
export function StatGrid({ items, loading }: { items: Stat[]; loading?: boolean }) {
  return (
    <dl
      className="m-0 grid overflow-hidden rounded-card border border-line bg-surface"
      style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
    >
      {items.map((s, i) => (
        <div
          key={s.label}
          className={cn(
            "flex flex-col-reverse justify-end gap-0.5 px-6 py-4",
            i > 0 && "border-l border-line",
          )}
        >
          {s.caption !== undefined && (
            <span className="order-first mt-0.5 text-xs text-subtle">{s.caption}</span>
          )}
          <dt className="text-[13px] text-muted">{s.label}</dt>
          <dd
            className={cn(
              "m-0 text-[26px] leading-tight font-bold tabular-nums",
              tone[s.tone ?? "ink"],
            )}
          >
            {loading ? <Skeleton className="my-1 h-6 w-16" /> : s.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
