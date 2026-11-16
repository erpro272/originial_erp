import { useState } from "react";
import { Link } from "react-router-dom";
import { KitIcon, KpiCard, Panel } from "@/components/kit/Kit";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { count, qty, rupeesCompact, shortDate } from "@/lib/format";
import { FactoryPanel } from "@/modules/production/FactoryPanel";
import { AlertsPanel } from "./Alerts";
import { presets, rangeLabel, useDashboard, useRange, withDemo, type Dashboard } from "./api";
import { CashFlowChart } from "./CashFlowChart";
import { OrderTimeline } from "./OrderTimeline";

function RangePicker({ from, to }: { from: string; to: string }) {
  const range = useRange();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(from);
  const [t, setT] = useState(to);
  const list = presets();
  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) {
          setF(from);
          setT(to);
        }
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Date range: ${rangeLabel(from, to)}`}
          className="flex cursor-pointer items-center gap-2.5 rounded-full border border-line bg-white px-4 py-2.5 text-[14px] font-medium text-ink shadow-sm hover:border-faint"
        >
          <KitIcon kind="calendar" className="size-4 text-ink-3" />
          {rangeLabel(from, to)}
          <span aria-hidden="true" className="text-ink-3">
            ▾
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[300px]">
        <div className="flex flex-col gap-1">
          {list.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => (
                range.set(
                  p.key === "two_weeks" ? null : p.from,
                  p.key === "two_weeks" ? null : p.to,
                ),
                setOpen(false)
              )}
              className={cn(
                "flex cursor-pointer justify-between rounded-md px-3 py-2 text-left text-[14px] hover:bg-surface",
                p.from === from && p.to === to && "bg-bl-bg font-semibold text-primary",
              )}
            >
              {p.label}
              <span className="text-[12px] text-muted">{rangeLabel(p.from, p.to)}</span>
            </button>
          ))}
        </div>
        <div className="mt-3 border-t border-divider pt-3">
          <div className="mb-2 text-[12px] font-semibold text-muted uppercase">Custom</div>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-[12px] text-ink-3">
              From
              <input
                type="date"
                value={f}
                max={t}
                onChange={(e) => setF(e.target.value)}
                className="rounded-md border border-line-input px-2 py-1.5 text-[13px]"
              />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-ink-3">
              To
              <input
                type="date"
                value={t}
                min={f}
                onChange={(e) => setT(e.target.value)}
                className="rounded-md border border-line-input px-2 py-1.5 text-[13px]"
              />
            </label>
          </div>
          <Button
            size="sm"
            className="mt-3 w-full"
            disabled={!f || !t || t < f}
            onClick={() => (range.set(f, t), setOpen(false))}
          >
            Apply
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function Kpis({ d }: { d: Dashboard }) {
  const [delayedOpen, setDelayedOpen] = useState(false);
  const k = d.kpis;
  const ip = k.in_progress;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label="Overall Utilization"
        value={k.utilization.value == null ? "—" : `${k.utilization.value}%`}
        note={k.utilization.note}
        tone="ok"
        icon="util"
        trend={k.utilization.trend}
      />
      <KpiCard
        label="In Progress"
        value={ip.value == null ? "—" : qty(ip.value, 0)}
        unit={ip.unit}
        note={ip.note}
        tone="bl"
        icon="wip"
      />
      <KpiCard
        label="Avg. Cycle Time"
        value={k.cycle_time.value == null ? "—" : k.cycle_time.value}
        unit={k.cycle_time.value == null ? undefined : k.cycle_time.unit}
        note={k.cycle_time.note}
        tone="ai"
        icon="cycle"
      />
      <KpiCard
        label="Delayed Orders"
        value={count(k.delayed.value ?? 0)}
        note={k.delayed_orders.length ? "Click to see which and why" : k.delayed.note}
        tone="hi"
        icon="alert"
        onClick={() => setDelayedOpen(true)}
      />
      <Modal
        open={delayedOpen}
        onOpenChange={setDelayedOpen}
        title="Delayed orders"
        description="Open orders past their due date, planned to finish after it, or behind schedule in Orders."
        width={600}
      >
        {k.delayed_orders.length === 0 ? (
          <p className="m-0 text-[14px] text-muted">Every open order is on track.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {k.delayed_orders.map((o) => (
              <li key={o.id}>
                <Link
                  to={`/orders?q=${o.number}`}
                  className="flex items-center justify-between gap-3 rounded-card border border-divider px-4 py-2.5 hover:bg-surface"
                >
                  <span className="flex flex-col">
                    <span className="font-semibold">
                      {o.number} · {o.customer}
                    </span>
                    <span className="text-[13px] text-hi">{o.reason}</span>
                  </span>
                  <span className="text-[13px] whitespace-nowrap text-muted">
                    Due {shortDate(o.due)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </div>
  );
}

function CustomerHealth({ d }: { d: Dashboard }) {
  const c = d.customers;
  const chips = [
    {
      key: "high_value",
      label: "High-value",
      value: c.high_value,
      cls: "bg-bl-bg text-bl border-bl-line",
    },
    { key: "repeat", label: "Repeat", value: c.repeat, cls: "bg-ok-bg text-ok border-ok-line" },
    {
      key: "inactive",
      label: "Inactive",
      value: c.inactive,
      cls: "bg-hi-bg text-hi border-hi-line",
    },
  ];
  return (
    <Panel id="customers-h" title="Customer Health & Priority Orders" icon="heart">
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-3 gap-3">
          {chips.map((x) => (
            <Link
              key={x.key}
              to={`/orders/customers?health=${x.key}`}
              className={cn(
                "flex flex-col items-center rounded-card border px-2 py-3 transition-shadow hover:shadow-md",
                x.cls,
              )}
            >
              <span className="text-[13px] font-medium">{x.label}</span>
              <span className="text-[24px] font-bold text-ink">{count(x.value)}</span>
            </Link>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          {c.top ? (
            <Link
              to={`/orders/customers/${c.top.id}`}
              className="flex flex-col rounded-card border border-line px-4 py-3 hover:bg-surface"
            >
              <span className="text-[13px] text-muted">Top Customer</span>
              <span className="truncate text-[16px] font-semibold text-ink">{c.top.name}</span>
              <span className="text-[12px] text-muted">
                {rupeesCompact(c.top.sales_paise)} sales
              </span>
            </Link>
          ) : (
            <div className="rounded-card border border-line px-4 py-3 text-[13px] text-muted">
              No sales yet
            </div>
          )}
          <Link
            to="/orders"
            className="flex items-center justify-between rounded-card border border-line px-4 py-3 hover:bg-surface"
          >
            <span className="flex flex-col">
              <span className="text-[13px] text-muted">Total Orders</span>
              <span className="text-[22px] font-bold text-ink">{count(c.total_orders)}</span>
            </span>
            <span aria-hidden="true" className="text-ink-3">
              →
            </span>
          </Link>
        </div>
        <p className="m-0 text-[12px] text-muted">
          {c.period_label} · rules from{" "}
          <Link to="/orders/customers" className="text-link">
            Customers
          </Link>
        </p>
      </div>
    </Panel>
  );
}

/** Dashboard: the owner's consolidated view. Everything is read from the other modules. */
export function DashboardPage() {
  const range = useRange();
  const q = useDashboard(range.from, range.to);
  const d = q.data;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-medium text-muted">Executive Overview</span>
          <h1 className="m-0 text-[34px] font-bold tracking-[-0.02em]">Operations Dashboard</h1>
          <p className="m-0 text-base text-muted">
            Real-time view of production, orders and business performance
          </p>
        </div>
        {d && <RangePicker from={d.range.start} to={d.range.end} />}
      </div>

      {q.isError ? (
        <EmptyState title="The dashboard couldn't load" description="Try again in a moment." />
      ) : !d ? (
        <div className="flex flex-col gap-6">
          <Skeleton className="h-24" />
          <Skeleton className="h-80" />
          <Skeleton className="h-96" />
        </div>
      ) : (
        <>
          <Kpis d={d} />
          <OrderTimeline d={d} />
          <FactoryPanel
            id="dash-factory-h"
            note={
              <p className="m-0 flex flex-wrap items-center justify-between gap-2 border-b border-divider bg-md-bg/30 px-6 py-2.5 text-[13px] text-md">
                Demo layout and numbers: the Production backend isn't connected yet. Hover an area
                to see its numbers.
                <Link to="/production" className="font-medium text-link">
                  Open Production →
                </Link>
              </p>
            }
          />
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.6fr_1fr]">
            <Panel
              id="cash-h"
              title="Cash Flow: Invoiced vs Collected & Payables (Last 6 Months)"
              icon="trend"
            >
              <CashFlowChart months={d.cash_flow} />
              <p className="m-0 mt-2 text-[12px] text-muted">
                Collected = money actually received (promises are not counted). Payables = supplier
                bills received; hover a month for what was actually paid.{" "}
                <Link to="/billing" className="text-link">
                  Open Billing →
                </Link>
              </p>
            </Panel>
            <CustomerHealth d={d} />
          </div>
          <AlertsPanel alerts={withDemo(d.alerts)} />
        </>
      )}
    </div>
  );
}
