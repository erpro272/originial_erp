import { useState } from "react";
import { Link } from "react-router-dom";
import { KitIcon, Panel } from "@/components/kit/Kit";
import { TipRow, Tooltip } from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { shortDate } from "@/lib/format";
import {
  parse,
  rowLink,
  type Dashboard,
  type MachineLoad,
  type Timeline,
  type TimelineRow,
} from "./api";

const STATUS: Record<string, { label: string; tone: TagTone }> = {
  new: { label: "New", tone: "lo" },
  accepted: { label: "Accepted", tone: "lo" },
  planned: { label: "Planned", tone: "bl" },
  in_production: { label: "In production", tone: "bl" },
  completed: { label: "Completed", tone: "ok" },
  shipped: { label: "Shipped", tone: "ok" },
  cancelled: { label: "Cancelled", tone: "lo" },
};

type Seg = "planned" | "elapsed" | "done" | "late";
const SEG: Record<Seg, { cls: string; label: string }> = {
  planned: { cls: "bg-primary/30", label: "Planned" },
  elapsed: { cls: "bg-primary", label: "In progress" },
  done: { cls: "bg-ok", label: "Completed" },
  late: { cls: "bg-hi/80", label: "Past due date" },
};

function kind(r: TimelineRow, day: string, today: string): Seg {
  if (r.status === "completed" || r.status === "shipped") return "done";
  if (r.due && day > r.due) return "late";
  if (day < today || (day === today && r.status === "in_production")) return "elapsed";
  return "planned";
}

function Gantt({ t, days, today }: { t: Timeline; days: string[]; today: string }) {
  const n = days.length;
  const col = `180px repeat(${n}, minmax(${n > 20 ? 36 : 64}px, 1fr))`;
  const todayIdx = days.indexOf(today);
  return (
    <div className="overflow-x-auto">
      <div className="min-w-fit" style={{ display: "grid", gridTemplateColumns: col }}>
        <div className="sticky left-0 z-10 flex items-end border-b border-line bg-card px-4 pb-2 text-[13px] font-semibold text-ink-2">
          Orders
        </div>
        {days.map((d) => {
          const dt = parse(d);
          return (
            <div
              key={d}
              className={cn(
                "border-b border-l border-divider px-1 py-2 text-center text-[12px] leading-tight text-ink-3",
                d === today && "bg-bl-bg/60 font-semibold text-primary",
                dt.getDay() === 0 && "bg-surface",
              )}
            >
              {dt.toLocaleDateString("en-GB", { weekday: "short" })}
              <br />
              {dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
            </div>
          );
        })}
        {t.rows.map((r) => {
          // contiguous runs of the same kind, clipped to the range
          const runs: { k: Seg; a: number; b: number }[] = [];
          days.forEach((d, i) => {
            if (d < r.start || d > r.finish) return;
            const k = kind(r, d, today);
            const last = runs[runs.length - 1];
            if (last && last.k === k && last.b === i - 1) last.b = i;
            else runs.push({ k, a: i, b: i });
          });
          const st = STATUS[r.status] ?? { label: r.status, tone: "lo" as const };
          return (
            <Link
              key={r.order_id}
              to={rowLink(t, r)}
              aria-label={`${r.number} · ${r.customer}: ${shortDate(r.start)} to ${shortDate(r.finish)}`}
              className="group contents"
            >
              <div className="sticky left-0 z-10 flex items-center gap-3 border-b border-divider bg-card px-4 py-3 group-hover:bg-surface">
                <span
                  className={cn(
                    "size-2 shrink-0 rounded-full",
                    r.late ? "bg-hi" : r.status === "in_production" ? "bg-primary" : "bg-faint",
                  )}
                />
                <span className="flex min-w-0 flex-col">
                  <span className="text-[14px] font-semibold text-ink">{r.number}</span>
                  <span className="truncate text-[12px] text-muted">{r.customer}</span>
                </span>
              </div>
              <div
                className="relative border-b border-divider group-hover:bg-surface/60"
                style={{ gridColumn: `2 / span ${n}` }}
              >
                <div
                  className="pointer-events-none absolute inset-0 grid"
                  style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}
                >
                  {days.map((d) => (
                    <span key={d} className="border-l border-divider" />
                  ))}
                </div>
                {todayIdx >= 0 && (
                  <span
                    className="pointer-events-none absolute inset-y-0 w-px bg-primary/50"
                    style={{ left: `${((todayIdx + 0.5) / n) * 100}%` }}
                  />
                )}
                <Tooltip
                  content={
                    <div className="min-w-[200px]">
                      <div className="mb-1 font-semibold">
                        {r.number} · {r.customer}
                      </div>
                      <TipRow label="Status" value={st.label} />
                      <TipRow
                        label="Scheduled"
                        value={`${shortDate(r.start)} – ${shortDate(r.finish)}`}
                      />
                      <TipRow label="Due" value={r.due ? shortDate(r.due) : "—"} />
                      {r.progress_pct != null && (
                        <TipRow label="Progress" value={`${r.progress_pct}%`} />
                      )}
                      {r.late && <TipRow label="Risk" value="Finishes after the due date" />}
                    </div>
                  }
                >
                  <span
                    className="absolute top-1/2 flex h-3.5 -translate-y-1/2 overflow-hidden rounded-full"
                    style={{
                      left: `${((runs[0]?.a ?? 0) / n) * 100 + 0.6}%`,
                      width: `${(((runs.at(-1)?.b ?? 0) - (runs[0]?.a ?? 0) + 1) / n) * 100 - 1.2}%`,
                    }}
                  >
                    {runs.map((x) => (
                      <span key={x.a} className={SEG[x.k].cls} style={{ flex: x.b - x.a + 1 }} />
                    ))}
                  </span>
                </Tooltip>
              </div>
            </Link>
          );
        })}
      </div>
      <ul className="m-0 mt-3 flex list-none flex-wrap gap-4 p-0 px-4 text-[12px] text-ink-3">
        {(Object.keys(SEG) as Seg[]).map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-4 rounded-full", SEG[k].cls)} />
            {SEG[k].label}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusTable({ t }: { t: Timeline }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[14px]">
        <thead>
          <tr className="text-left text-[12px] tracking-wide text-muted uppercase">
            {["Order", "Customer", "Status", "Scheduled", "Due", "Progress"].map((h) => (
              <th key={h} className="border-b border-line px-4 py-2 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {t.rows.map((r) => {
            const st = STATUS[r.status] ?? { label: r.status, tone: "lo" as const };
            return (
              <tr key={r.order_id} className="hover:bg-surface">
                <td className="border-b border-divider px-4 py-2.5 font-semibold">
                  <Link to={rowLink(t, r)} className="text-link hover:underline">
                    {r.number}
                  </Link>
                </td>
                <td className="border-b border-divider px-4 py-2.5">{r.customer}</td>
                <td className="border-b border-divider px-4 py-2.5">
                  <span className="flex gap-1.5">
                    <Tag tone={st.tone} size="sm">
                      {st.label}
                    </Tag>
                    {r.late && (
                      <Tag tone="hi" size="sm">
                        Late risk
                      </Tag>
                    )}
                  </span>
                </td>
                <td className="border-b border-divider px-4 py-2.5 whitespace-nowrap">
                  {shortDate(r.start)} – {shortDate(r.finish)}
                </td>
                <td className="border-b border-divider px-4 py-2.5 whitespace-nowrap">
                  {r.due ? shortDate(r.due) : "—"}
                </td>
                <td className="border-b border-divider px-4 py-2.5">
                  {r.progress_pct != null ? `${r.progress_pct}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LoadBar({ m, scale }: { m: MachineLoad; scale: number }) {
  const cur = m.current ?? 0;
  const aft = m.after ?? 0;
  const w = (v: number) => `${(Math.min(v, scale) / scale) * 100}%`;
  return (
    <span className="relative block h-3 w-full rounded-full bg-surface-2">
      <span
        className={cn(
          "absolute inset-y-0 left-0 rounded-full",
          m.over ? "bg-hi/25" : "bg-primary/30",
        )}
        style={{ width: w(Math.max(aft, cur)) }}
      />
      <span
        className={cn(
          "absolute inset-y-0 left-0 rounded-full",
          m.over ? "bg-hi/70" : "bg-primary/80",
        )}
        style={{ width: w(cur) }}
      />
      <span className="absolute -inset-y-0.5 w-px bg-ink-3/40" style={{ left: w(100) }} />
    </span>
  );
}

function MachineDialog({ m, t, onClose }: { m: MachineLoad; t: Timeline; onClose: () => void }) {
  const plan = t.draft ?? t.plan;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`${m.name} · machine load`}
      description={
        m.over
          ? `Over capacity after the new orders: ${m.peak_after}% on ${m.peak_day ? shortDate(m.peak_day) : "—"}.`
          : (m.peak_after ?? 0) >= 100
            ? "Fully booked on some days after the new orders: Planning pushes any further work later."
            : "Within capacity in this period."
      }
      width={640}
      footer={
        plan && (
          <Link to={`/planning/${plan.id}?step=3`} className="text-[14px] font-medium text-link">
            Open {plan.number}'s schedule in Planning →
          </Link>
        )
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-card border border-line px-4 py-3">
          <div className="text-[13px] text-muted">Current Plan (average)</div>
          <div className="text-[22px] font-bold">{m.current ?? "—"}%</div>
        </div>
        <div
          className={cn(
            "rounded-card border px-4 py-3",
            m.over ? "border-hi-line bg-hi-bg/40" : "border-line",
          )}
        >
          <div className="text-[13px] text-muted">After New Orders (average)</div>
          <div className={cn("text-[22px] font-bold", m.over && "text-hi")}>{m.after ?? "—"}%</div>
        </div>
      </div>
      <div>
        <h3 className="m-0 mb-2 text-[14px] font-semibold">Day by day</h3>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-muted">
                <th className="border-b border-line py-1.5 font-medium">Day</th>
                <th className="border-b border-line py-1.5 text-right font-medium">Current Plan</th>
                <th className="border-b border-line py-1.5 text-right font-medium">
                  After New Orders
                </th>
              </tr>
            </thead>
            <tbody>
              {m.days
                .filter((d) => d.after != null)
                .map((d) => (
                  <tr key={d.day}>
                    <td className="border-b border-divider py-1.5">{shortDate(d.day)}</td>
                    <td className="border-b border-divider py-1.5 text-right">{d.current}%</td>
                    <td
                      className={cn(
                        "border-b border-divider py-1.5 text-right",
                        (d.after ?? 0) > 100 && "font-semibold text-hi",
                      )}
                    >
                      {d.after}%
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <h3 className="m-0 mb-2 text-[14px] font-semibold">Orders on this machine in the period</h3>
        {m.orders.length === 0 ? (
          <p className="m-0 text-[13px] text-muted">Nothing scheduled.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]">
            {m.orders.map((o) => (
              <li key={o.number} className="flex items-center justify-between gap-3">
                <span>
                  <span className="font-semibold">{o.number}</span> · {o.customer}{" "}
                  {o.added && (
                    <Tag tone="md" size="sm">
                      New order{t.draft ? ` · ${t.draft.number}` : ""}
                    </Tag>
                  )}
                </span>
                <span className="text-ink-3">{o.hours} h</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}

function Machines({ t }: { t: Timeline }) {
  const [open, setOpen] = useState<MachineLoad | null>(null);
  const shown = t.machines.filter((m) => m.after != null);
  const scale = Math.max(150, ...shown.map((m) => m.after ?? 0));
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-divider px-5 py-3">
        <h3 className="m-0 flex items-center gap-2 text-[15px] font-semibold">
          <KitIcon kind="gear" className="size-5 text-ink-2" />
          Machine Load
        </h3>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-5 pt-3 text-[12px] text-ink-3">
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-primary/80" />
          Current Plan
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-hi/70" />
          After New Orders
        </span>
      </div>
      {shown.length === 0 ? (
        <p className="m-0 px-5 py-6 text-[13px] text-muted">
          No machine time scheduled in this period.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1 p-3">
          {shown.map((m) => (
            <li key={m.machine}>
              <button
                type="button"
                onClick={() => setOpen(m)}
                aria-label={`${m.name}: current plan ${m.current}%, after new orders ${m.after}%${m.over ? ", over capacity" : ""}`}
                className="grid w-full cursor-pointer grid-cols-[76px_1fr_64px] items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-surface"
              >
                <span className="truncate text-[13px] text-ink-2">{m.name}</span>
                <LoadBar m={m} scale={scale} />
                <span
                  className={cn(
                    "flex items-center justify-end gap-1 text-[13px] font-semibold",
                    m.over ? "text-hi" : (m.peak_after ?? 0) >= 100 ? "text-md" : "text-ink",
                  )}
                  title={
                    m.over
                      ? `Over capacity: peak ${m.peak_after}%`
                      : (m.peak_after ?? 0) >= 100
                        ? "Fully booked on some days: more work would be pushed later"
                        : undefined
                  }
                >
                  {m.over ? m.peak_after : m.after}%
                  {(m.over || (m.peak_after ?? 0) >= 100) && (
                    <KitIcon kind="alert" className="size-3.5" />
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="m-0 mt-auto px-5 pb-4 text-[12px] text-muted">
        Average over the working days of the period; a warning shows the busiest day. Click a
        machine for the detail.
      </p>
      {open && <MachineDialog m={open} t={t} onClose={() => setOpen(null)} />}
    </div>
  );
}

function SourceNote({ t }: { t: Timeline }) {
  return (
    <div className="flex flex-col gap-1 border-b border-divider px-6 py-3 text-[13px] text-ink-3">
      {t.source === "approved" && t.plan && (
        <span>
          Mirrors the approved schedule of{" "}
          <Link to={`/planning/${t.plan.id}`} className="font-medium text-link">
            {t.plan.number}
          </Link>
          {t.plan.approved_at && ` (approved ${shortDate(t.plan.approved_at)})`}.
          {t.plan.needs_reapproval && (
            <Tag tone="md" size="sm" className="ml-2">
              Needs re-approval
            </Tag>
          )}
        </span>
      )}
      {t.source === "committed" && (
        <span>
          No approved plan yet: showing the work already committed (orders in production), as
          Planning schedules it.
        </span>
      )}
      {t.draft && t.draft.orders.length > 0 && (
        <span>
          <Link to={`/planning/${t.draft.id}`} className="font-medium text-link">
            {t.draft.number}
          </Link>{" "}
          has {t.draft.orders.length} new order{t.draft.orders.length === 1 ? "" : "s"} not approved
          yet ({t.draft.orders.join(", ")}): they appear in Machine Load as After New Orders, not on
          the timeline.
        </span>
      )}
    </div>
  );
}

/** Order Timeline: 80% Gantt (mirror of Planning's schedule) + 20% Machine Load (Current Plan vs After New Orders). */
export function OrderTimeline({ d }: { d: Dashboard }) {
  const [view, setView] = useState<"gantt" | "status">("gantt");
  const t = d.timeline;
  return (
    <Panel
      id="timeline-h"
      title="Order Timeline"
      icon="calendar"
      bodyClassName="p-0"
      aside={
        <SegmentedControl
          label="Gantt or status view"
          value={view}
          onChange={setView}
          options={[
            { value: "gantt" as const, label: "Gantt View" },
            { value: "status" as const, label: "Status View" },
          ]}
        />
      }
    >
      <div className="grid grid-cols-1 xl:grid-cols-[4fr_minmax(280px,1fr)]">
        <div className="min-w-0 border-divider xl:border-r">
          <SourceNote t={t} />
          {t.rows.length === 0 ? (
            <p className="m-0 px-6 py-10 text-center text-[14px] text-muted">
              Nothing scheduled in this period.{" "}
              <Link to="/planning" className="font-medium text-link">
                Open Planning →
              </Link>
            </p>
          ) : (
            <div className="py-3">
              {view === "gantt" ? (
                <Gantt t={t} days={d.range.days} today={d.range.today} />
              ) : (
                <StatusTable t={t} />
              )}
            </div>
          )}
        </div>
        <div className="border-t border-divider xl:border-t-0">
          <Machines t={t} />
        </div>
      </div>
    </Panel>
  );
}
