import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { TONE, type Tone } from "./tones";

/** Decorative trend line (the numbers are in the card's text). Draws nothing for fewer than 2 points. */
export function Sparkline({
  data,
  tone,
  className,
}: {
  data: readonly number[];
  tone: Tone;
  className?: string;
}) {
  if (data.length < 2) return <span className={className} aria-hidden="true" />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * 100},${28 - ((v - min) / (max - min || 1)) * 24}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={className} aria-hidden="true">
      <polyline
        points={pts}
        fill="none"
        className={TONE[tone].stroke}
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** 24px line icon (currentColor). */
export function Icon({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export type IconKind =
  | "util"
  | "wip"
  | "cycle"
  | "alert"
  | "info"
  | "map"
  | "bars"
  | "bell"
  | "calendar"
  | "gear"
  | "heart"
  | "trend"
  | "upload";

const PATHS: Record<IconKind, ReactNode> = {
  util: <path d="M3 20h18M5 20v-7l4-3 4 3 6-6M5 9V5h4" />,
  wip: (
    <>
      <path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z" />
      <path d="M3.5 7 12 11.5 20.5 7M12 11.5v10" />
    </>
  ),
  cycle: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  alert: <path d="M12 3 22 20H2zM12 10v4M12 17v.5" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7.5v.5" />
    </>
  ),
  map: <path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15M15 6v15" />,
  bars: <path d="M4 20V10M10 20V4M16 20v-7M2 20h20" />,
  bell: <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0" />,
  calendar: (
    <>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </>
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
    </>
  ),
  heart: <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />,
  trend: <path d="M3 17l6-6 4 4 8-8M15 7h6v6" />,
  upload: <path d="M12 16V4M7 9l5-5 5 5M4 16v4h16v-4" />,
};

export function KitIcon({ kind, className }: { kind: IconKind; className?: string }) {
  return <Icon className={className}>{PATHS[kind]}</Icon>;
}

/** KPI card: tinted icon circle, label, big value (+ unit, delta), optional note, sparkline. */
export function KpiCard({
  label,
  value,
  unit,
  delta,
  note,
  tone,
  icon,
  trend = [],
  onClick,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  delta?: ReactNode;
  note?: string;
  tone: Tone;
  icon: IconKind;
  trend?: readonly number[];
  onClick?: () => void;
}) {
  const body = (
    <>
      <span
        className={cn("grid size-12 shrink-0 place-items-center rounded-full", TONE[tone].icon)}
      >
        <KitIcon kind={icon} className="size-6" />
      </span>
      <div className="flex shrink-0 flex-col text-left">
        <span className="text-[14px] font-medium whitespace-nowrap text-ink-2">{label}</span>
        <span className="flex items-baseline gap-1.5 text-[24px] font-bold whitespace-nowrap text-ink">
          {value}
          {unit && <span className="text-[18px] font-semibold">{unit}</span>}
          {delta && <span className="text-[13px] font-semibold text-ok">{delta}</span>}
        </span>
        {note && <span className="max-w-[220px] text-[12px] leading-snug text-muted">{note}</span>}
      </div>
      <Sparkline data={trend} tone={tone} className="ml-auto h-8 min-w-0 flex-1 basis-0" />
    </>
  );
  const cls = cn("flex items-center gap-4 rounded-card border px-5 py-4", TONE[tone].card);
  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      className={cn(cls, "cursor-pointer text-left transition-shadow hover:shadow-md")}
    >
      {body}
    </button>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/** White section card with an icon title row and optional right-side controls. */
export function Panel({
  id,
  title,
  icon,
  aside,
  children,
  className,
  bodyClassName,
}: {
  id: string;
  title: ReactNode;
  icon: IconKind;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      aria-labelledby={id}
      className={cn("rounded-card border border-line bg-white", className)}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-divider px-6 py-4">
        <h2 id={id} className="m-0 flex items-center gap-3 text-[18px] font-semibold">
          <KitIcon kind={icon} className="size-6 text-ink-2" />
          {title}
        </h2>
        {aside}
      </header>
      <div className={cn("p-6", bodyClassName)}>{children}</div>
    </section>
  );
}
