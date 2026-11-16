import { useState } from "react";
import { Link } from "react-router-dom";
import { KitIcon, Panel } from "@/components/kit/Kit";
import { TONE } from "@/components/kit/tones";
import { FilterChips } from "@/components/ui/FilterChips";
import { Sheet } from "@/components/ui/Sheet";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { shortDate } from "@/lib/format";
import type { Alert, DashAlert } from "./api";

const SOURCE: Record<Alert["source"], string> = {
  planning: "Planning",
  orders: "Orders",
  production: "Production",
  purchasing: "Purchasing",
  billing: "Billing",
};

function AlertRow({ a }: { a: DashAlert }) {
  return (
    <li>
      <Link
        to={a.link}
        className="flex items-center gap-4 rounded-card border border-divider px-4 py-2.5 transition-colors hover:border-line hover:bg-surface"
      >
        <span
          className={cn("grid size-10 shrink-0 place-items-center rounded-full", TONE[a.tone].icon)}
        >
          <KitIcon
            kind={a.tone === "hi" || a.tone === "md" ? "alert" : "info"}
            className="size-5"
          />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[15px] font-semibold text-ink">{a.title}</span>
          <span className="truncate text-[13px] text-muted">{a.text}</span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-[12px] text-muted">{a.time ?? (a.at ? shortDate(a.at) : "")}</span>
          <Tag tone="lo" size="sm">
            {SOURCE[a.source]}
            {a.demo ? " · demo" : ""}
          </Tag>
        </span>
      </Link>
    </li>
  );
}

export function AlertsPanel({ alerts }: { alerts: DashAlert[] }) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<Alert["source"] | "all">("all");
  const list = source === "all" ? alerts : alerts.filter((a) => a.source === source);
  return (
    <Panel
      id="alerts-h"
      title="Alerts & Updates"
      icon="bell"
      className="flex flex-col"
      aside={
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="cursor-pointer text-[13px] font-medium text-link hover:underline"
        >
          View All ({alerts.length}) →
        </button>
      }
    >
      {alerts.length === 0 ? (
        <p className="m-0 text-[14px] text-muted">Nothing needs your attention.</p>
      ) : (
        <ul className="m-0 grid list-none grid-cols-1 gap-2 p-0 lg:grid-cols-2">
          {alerts.slice(0, 6).map((a) => (
            <AlertRow key={a.id} a={a} />
          ))}
        </ul>
      )}
      <Sheet
        open={open}
        onOpenChange={setOpen}
        eyebrow="Executive Dashboard"
        title="Alerts & Updates"
        description="Each alert opens the record it came from."
        width={620}
      >
        <div className="flex flex-col gap-4">
          <FilterChips
            label="Filter alerts by module"
            value={source}
            onChange={setSource}
            options={[
              { value: "all", label: "All", count: alerts.length },
              ...(Object.keys(SOURCE) as Alert["source"][])
                .map((s) => ({
                  value: s,
                  label: SOURCE[s],
                  count: alerts.filter((a) => a.source === s).length,
                }))
                .filter((o) => o.count > 0),
            ]}
          />
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {list.map((a) => (
              <AlertRow key={a.id} a={a} />
            ))}
          </ul>
        </div>
      </Sheet>
    </Panel>
  );
}
