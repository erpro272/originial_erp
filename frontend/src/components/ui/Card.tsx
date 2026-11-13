import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

type Accent = "none" | "hi" | "md";
const accent: Record<Accent, string> = {
  none: "border-line",
  hi: "border-hi-line",
  md: "border-md-line",
};

/** 16px-radius bordered card. `accent` tints the border like the priority cards. */
export function Card({
  className,
  accent: a = "none",
  ...props
}: HTMLAttributes<HTMLElement> & { accent?: Accent }) {
  return (
    <section className={cn("rounded-card border bg-white", accent[a], className)} {...props} />
  );
}

/** Card header row: 17px title (+ optional muted suffix) and right-side actions. */
export function CardHeader({
  title,
  suffix,
  actions,
  className,
}: {
  title: ReactNode;
  suffix?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("flex flex-wrap items-center justify-between gap-3 px-5 py-[18px]", className)}
    >
      <h2 className="m-0 text-[17px] font-semibold">
        {title}
        {suffix && <small className="ml-1.5 text-[13px] font-normal text-muted">{suffix}</small>}
      </h2>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Small uppercase section label ("NEEDS ATTENTION"). */
export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h2
      className={cn(
        "m-0 text-[13px] font-semibold tracking-[.06em] text-muted uppercase",
        className,
      )}
    >
      {children}
    </h2>
  );
}
