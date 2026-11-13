import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Skeleton } from "./Skeleton";

export type KpiTone = "ink" | "hi" | "bl" | "md" | "ok";
const toneClass: Record<KpiTone, string> = {
  ink: "text-ink",
  hi: "text-hi",
  bl: "text-bl",
  md: "text-md",
  ok: "text-ok",
};

export interface Kpi {
  label: string;
  value: ReactNode;
  tone?: KpiTone;
}

/** The joined KPI strip from the mockups (surface background, dividers between items). */
export function KpiStrip({
  items,
  loading,
  className,
}: {
  items: Kpi[];
  loading?: boolean;
  className?: string;
}) {
  return (
    <dl
      className={cn(
        "m-0 inline-flex max-w-full flex-wrap self-start overflow-hidden rounded-card border border-line bg-surface",
        className,
      )}
    >
      {items.map((k, i) => (
        <div
          key={k.label}
          className={cn(
            "flex flex-col-reverse justify-end gap-0.5 px-6 py-3.5",
            i > 0 && "border-l border-line",
          )}
        >
          <dt className="text-[13px] text-muted">{k.label}</dt>
          <dd className={cn("m-0 text-[26px] leading-tight font-bold", toneClass[k.tone ?? "ink"])}>
            {loading ? <Skeleton className="my-1 h-6 w-12" /> : k.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
