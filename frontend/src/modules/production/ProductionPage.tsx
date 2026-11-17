import { useEffect, useState } from "react";
import { Icon, KitIcon, KpiCard, Sparkline } from "@/components/kit/Kit";
import { TONE } from "@/components/kit/tones";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { ALERTS, DEMO_NOTICE, KPIS, SECTIONS } from "./demoData";
import { FactoryPanel } from "./FactoryPanel";

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
    <div className="flex items-center rounded-full border border-line bg-card text-[13px]">
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

const ICONS = { util: "util", wip: "wip", cycle: "cycle", delayed: "alert" } as const;

/** Production → Factory Layout. Frontend preview on demo data (see demoData.ts). */
export function ProductionPage() {
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
              <KitIcon kind="upload" className="size-4" />
              Upload Document
            </Button>
          </div>
          <LiveClock />
        </div>
      </div>

      <p className="m-0 rounded-card border border-dashed border-md-line bg-md-bg/40 px-4 py-2 text-[13px] text-md">
        {DEMO_NOTICE} Hover a stage or station to see its numbers.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {KPIS.map((k) => (
          <KpiCard
            key={k.key}
            label={k.label}
            value={k.value}
            unit={"unit" in k ? k.unit : undefined}
            delta={"delta" in k ? `↑ ${k.delta}` : undefined}
            tone={k.tone}
            icon={ICONS[k.key]}
            trend={k.trend}
          />
        ))}
      </div>

      <FactoryPanel id="layout-h" />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]">
        <section aria-labelledby="perf-h" className="rounded-card border border-line bg-card p-5">
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
        <section aria-labelledby="alerts-h" className="rounded-card border border-line bg-card p-5">
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
                  <KitIcon kind={a.tone === "hi" ? "alert" : "info"} className="size-5" />
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
