import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { cn } from "@/lib/cn";
import { ALERTS, DEMO_NOTICE, KPIS, SECTIONS } from "./demoData";
import { FactoryLayout } from "./FactoryLayout";
import { STATUS } from "./status";

type Tone = "ok" | "bl" | "ai" | "hi" | "md";
const TONE: Record<Tone, { stroke: string; icon: string; card: string }> = {
  ok: { stroke: "stroke-ok", icon: "bg-ok-bg text-ok", card: "bg-ok-bg/40 border-ok-line/60" },
  bl: {
    stroke: "stroke-primary",
    icon: "bg-bl-bg text-primary",
    card: "bg-bl-bg/40 border-bl-line/60",
  },
  ai: { stroke: "stroke-ai", icon: "bg-ai-bg text-ai", card: "bg-ai-bg/40 border-ai-line" },
  hi: { stroke: "stroke-hi", icon: "bg-hi-bg text-hi", card: "bg-hi-bg/40 border-hi-line/60" },
  md: {
    stroke: "stroke-md-accent",
    icon: "bg-md-bg text-md",
    card: "bg-md-bg/40 border-md-line/60",
  },
};

/** Decorative trend line (the numbers are in the card's text). */
function Sparkline({
  data,
  tone,
  className,
}: {
  data: readonly number[];
  tone: Tone;
  className?: string;
}) {
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

const KPI_ICON: Record<string, ReactNode> = {
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
  delayed: <path d="M12 3 22 20H2zM12 10v4M12 17v.5" />,
};

function Icon({ children, className }: { children: ReactNode; className?: string }) {
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

function LiveClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  const time = now.toLocaleTimeString("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  const date = now.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return (
    <div className="flex items-center rounded-full border border-line bg-white text-[13px]">
      <span className="flex items-center gap-2 border-r border-line px-4 py-2 font-semibold text-ink">
        <span className="size-2 rounded-full bg-ok" />
        Live
      </span>
      <span className="px-4 py-2 text-ink-2">
        {time.toUpperCase()} · {date}
      </span>
    </div>
  );
}

/** Production → Factory Layout. Frontend preview on demo data (see demoData.ts). */
export function ProductionPage() {
  const [view, setView] = useState<"layout" | "status">("layout");
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-medium text-muted">Production</span>
          <h1 className="m-0 text-[34px] font-bold tracking-[-0.02em]">Factory Layout</h1>
          <p className="m-0 text-base text-muted">
            Live view of workstations, production flow and current status
          </p>
        </div>
        <div className="flex flex-col items-end gap-3">
          <div className="flex gap-3">
            <Button variant="dark" title={DEMO_NOTICE}>
              + New Order
            </Button>
            <Button variant="pill" size="md" title={DEMO_NOTICE}>
              <Icon className="size-4">
                <path d="M12 16V4M7 9l5-5 5 5M4 16v4h16v-4" />
              </Icon>
              Upload Document
            </Button>
          </div>
          <LiveClock />
        </div>
      </div>

      <p className="m-0 rounded-card border border-dashed border-md-line bg-md-bg/40 px-4 py-2 text-[13px] text-md">
        {DEMO_NOTICE} Hover a stage or station to see its numbers.
      </p>

      <dl className="m-0 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {KPIS.map((k) => (
          <div
            key={k.key}
            className={cn(
              "flex items-center gap-4 rounded-card border px-5 py-4",
              TONE[k.tone].card,
            )}
          >
            <span
              className={cn(
                "grid size-12 shrink-0 place-items-center rounded-full",
                TONE[k.tone].icon,
              )}
            >
              <Icon className="size-6">{KPI_ICON[k.key]}</Icon>
            </span>
            <div className="flex shrink-0 flex-col">
              <dt className="text-[14px] font-medium whitespace-nowrap text-ink-2">{k.label}</dt>
              <dd className="m-0 flex items-baseline gap-1.5 text-[24px] font-bold whitespace-nowrap text-ink">
                {k.value}
                {"unit" in k && <span className="text-[18px] font-semibold">{k.unit}</span>}
                {"delta" in k && (
                  <span className="text-[13px] font-semibold text-ok">↑ {k.delta}</span>
                )}
              </dd>
            </div>
            <Sparkline
              data={k.trend}
              tone={k.tone}
              className="ml-auto h-8 min-w-0 flex-1 basis-0"
            />
          </div>
        ))}
      </dl>

      <section aria-labelledby="layout-h" className="rounded-card border border-line bg-white">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-divider px-6 py-4">
          <h2 id="layout-h" className="m-0 flex items-center gap-3 text-[19px] font-semibold">
            <Icon className="size-6 text-ink-2">
              <path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15M15 6v15" />
            </Icon>
            Factory Layout
          </h2>
          <SegmentedControl
            label="Layout or status view"
            value={view}
            onChange={(v) => setView(v as "layout" | "status")}
            options={[
              { value: "layout", label: "Layout View" },
              { value: "status", label: "Status View" },
            ]}
          />
        </header>
        <div className="flex gap-6 overflow-x-auto p-6">
          <div className="flex-1">
            <FactoryLayout view={view} />
          </div>
          <ul className="m-0 flex h-fit shrink-0 list-none flex-col gap-3 rounded-card border border-line p-4 text-[13px] text-ink-2 shadow-sm">
            {(["running", "idle", "maintenance", "issue"] as const).map((s) => (
              <li key={s} className="flex items-center gap-3">
                <span className={cn("size-3 rounded-full", STATUS[s].dot)} />
                {STATUS[s].label}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]">
        <section aria-labelledby="perf-h" className="rounded-card border border-line bg-white p-5">
          <h2 id="perf-h" className="m-0 mb-4 flex items-center gap-3 text-[18px] font-semibold">
            <Icon className="size-6 text-ink-2">
              <path d="M4 20V10M10 20V4M16 20v-7M2 20h20" />
            </Icon>
            Section Performance
          </h2>
          <dl className="m-0 grid grid-cols-2 gap-3 md:grid-cols-4">
            {SECTIONS.map((s) => (
              <div
                key={s.label}
                className={cn(
                  "flex flex-col rounded-card border px-4 pt-3 pb-2",
                  TONE[s.tone].card,
                )}
              >
                <dt className="text-[13px] text-ink-2">{s.label}</dt>
                <dd className="m-0 text-[22px] font-bold text-ink">{s.value}%</dd>
                <Sparkline data={s.trend} tone={s.tone} className="mt-1 h-8 w-full" />
              </div>
            ))}
          </dl>
        </section>
        <section
          aria-labelledby="alerts-h"
          className="rounded-card border border-line bg-white p-5"
        >
          <div className="mb-3 flex items-center justify-between">
            <h2 id="alerts-h" className="m-0 flex items-center gap-3 text-[18px] font-semibold">
              <Icon className="size-6 text-ink-2">
                <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0" />
              </Icon>
              Alerts &amp; Updates
            </h2>
            <span className="text-[13px] font-medium text-link" title={DEMO_NOTICE}>
              View All →
            </span>
          </div>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {ALERTS.map((a) => (
              <li
                key={a.title}
                className="flex items-center gap-4 rounded-card border border-divider px-4 py-2.5"
              >
                <span
                  className={cn(
                    "grid size-10 shrink-0 place-items-center rounded-full",
                    TONE[a.tone].icon,
                  )}
                >
                  <Icon className="size-5">
                    {a.tone === "hi" ? (
                      KPI_ICON.delayed
                    ) : (
                      <>
                        <circle cx="12" cy="12" r="9" />
                        <path d="M12 11v6M12 7.5v.5" />
                      </>
                    )}
                  </Icon>
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="text-[15px] font-semibold text-ink">{a.title}</span>
                  <span className="text-[13px] text-muted">{a.text}</span>
                </div>
                <span className="text-[13px] text-muted">{a.at}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
