import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { AssistantBadge } from "@/components/ui/AssistantBadge";
import { Button } from "@/components/ui/Button";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { count, dateTime, rupeesCompact, shortDate } from "@/lib/format";
import { useGenerate, usePatchPlan, type SelectionOption } from "../api";
import { Flash } from "../bits";
import { dayParts, plural, range } from "../format";
import type { TabProps } from "../PlanningPage";

type OptKey = "own" | "part" | "full";
const OPT_LABEL: Record<OptKey, string> = {
  own: "Your selection",
  part: "Partly optimized",
  full: "Fully optimized",
};
const PRI_TONE: Record<string, TagTone> = { high: "hi", medium: "md", low: "lo" };
const PRI_LABEL: Record<string, string> = { high: "High", medium: "Medium", low: "Low" };

export function SelectedOrdersTab({ plan, go }: TabProps) {
  const { can } = useAuth();
  const edit = can("planning.write");
  const sel = plan.result.selection;
  const patch = usePatchPlan(plan.id);
  const gen = useGenerate(plan.id);
  const { toast } = useToast();
  const [sort, setSort] = useState<"deadline" | "value" | "margin">("deadline");
  const [hover, setHover] = useState<OptKey>("own");
  // Show the tick at once while the server recalculates the plan.
  const [pendingSel, setPendingSel] = useState<string[] | null>(null);
  const current = pendingSel ?? sel.selected;
  const selected = new Set(current);
  const opts = sel.options;
  const suggested = new Set([...(opts.part?.orders ?? []), ...(opts.full?.orders ?? [])]);

  const rows = useMemo(() => {
    const all = Object.entries(sel.orders).map(([id, o]) => ({ id, ...o }));
    const key = {
      deadline: (o: (typeof all)[number]) => o.deadline,
      value: (o: (typeof all)[number]) => String(1e15 - o.value).padStart(16, "0"),
      margin: (o: (typeof all)[number]) => String(1000 - o.est_margin).padStart(8, "0"),
    }[sort];
    return all.sort((a, b) => key(a).localeCompare(key(b)));
  }, [sel.orders, sort]);

  const run = async (body: Parameters<typeof patch.mutateAsync>[0], ok?: string) => {
    try {
      await patch.mutateAsync(body);
      if (ok) toast({ title: ok, tone: "success" });
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't update the plan.",
        tone: "error",
      });
    }
  };
  const toggle = async (id: string, on: boolean) => {
    const next = on ? [...current, id] : current.filter((x) => x !== id);
    setPendingSel(next);
    await run({ selected: next });
    setPendingSel(null);
  };

  const picked = rows.filter((r) => selected.has(r.id));
  const totals = {
    qty: picked.reduce((s, r) => s + r.qty, 0),
    value: picked.reduce((s, r) => s + r.value, 0),
    contribution: opts.own?.contribution ?? 0,
  };

  return (
    <section className="flex flex-col gap-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Selected orders</h2>
          <p className="m-0 text-sm text-muted">
            Pulled from <Link to="/orders">Orders received</Link>. Add or remove orders to change
            the combination that gets planned.
          </p>
        </div>
      </div>

      <OrderTimeline plan={plan} hover={hover} />

      {/* the orders */}
      <section className="overflow-hidden rounded-card border border-line">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex items-center gap-2.5">
            <h3 className="m-0 text-[17px] font-semibold">In this plan</h3>
            <Tag tone="lo">
              {picked.length} of {rows.length}
            </Tag>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="flex items-center gap-2 text-[13px] text-ink-2">
              <span className="sr-only">Sort</span>
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as typeof sort)}
                className="cursor-pointer rounded-full border border-line-input bg-white px-3.5 py-2 text-[13px] font-medium text-ink-2"
              >
                <option value="deadline">Sort: Deadline</option>
                <option value="value">Sort: Value</option>
                <option value="margin">Sort: Est. margin</option>
              </select>
            </label>
            <Button asChild variant="pill" size="pill">
              <Link to="/orders">+ Add from Orders received</Link>
            </Button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead className="bg-surface">
              <tr className="text-left text-xs font-semibold tracking-[0.04em] text-muted uppercase">
                <th className="w-10 px-4 py-3">
                  <span className="sr-only">Include</span>
                </th>
                <th className="px-4 py-3">Order</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Product</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3 text-right">Quantity</th>
                <th className="px-4 py-3 text-right">Value</th>
                <th className="px-4 py-3">Deadline</th>
                <th className="px-4 py-3 text-right">Est. margin</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const on = selected.has(r.id);
                return (
                  <tr
                    key={r.id}
                    className={cn("border-t border-divider text-sm", !on && "text-subtle")}
                  >
                    <td className="px-4 py-3.5">
                      <input
                        type="checkbox"
                        className="size-4 accent-primary"
                        checked={on}
                        disabled={!edit || patch.isPending}
                        aria-label={`Include ${r.number}`}
                        onChange={(e) => void toggle(r.id, e.target.checked)}
                      />
                    </td>
                    <td className="px-4 py-3.5 font-mono">{r.number}</td>
                    <td className="px-4 py-3.5">{r.customer}</td>
                    <td className="px-4 py-3.5">{r.product}</td>
                    <td className={cn("px-4 py-3.5", !on && "opacity-55")}>
                      <Tag tone={PRI_TONE[r.priority] ?? "lo"}>
                        {PRI_LABEL[r.priority] ?? r.priority}
                      </Tag>
                    </td>
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      {count(r.qty)} {r.unit}
                    </td>
                    <td className="px-4 py-3.5 text-right">{rupeesCompact(r.value)}</td>
                    <td className="px-4 py-3.5 whitespace-nowrap">{shortDate(r.deadline)}</td>
                    <td className="px-4 py-3.5 text-right">
                      <Flash value={r.est_margin}>{r.est_margin}%</Flash>
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      {on ? (
                        edit && (
                          <button
                            type="button"
                            aria-label={`Remove ${r.number}`}
                            onClick={() => void toggle(r.id, false)}
                            className="cursor-pointer rounded-lg border-0 bg-transparent px-2 py-1 text-lg leading-none text-subtle hover:bg-hi-bg hover:text-hi"
                          >
                            ×
                          </button>
                        )
                      ) : suggested.has(r.id) ? (
                        <Tag tone="ok">Suggested</Tag>
                      ) : (
                        <span className="text-[13px]">Excluded</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap justify-between gap-3 border-t border-line bg-surface px-5 py-3.5 text-sm">
          <span className="text-muted">Total for {plural(picked.length, "order")}</span>
          <span className="flex flex-wrap gap-6">
            <span>
              Qty{" "}
              <b>
                <Flash value={totals.qty}>{count(totals.qty)} pcs</Flash>
              </b>
            </span>
            <span>
              Value{" "}
              <b>
                <Flash value={totals.value}>{rupeesCompact(totals.value)}</Flash>
              </b>
            </span>
            <span>
              Est. contribution{" "}
              <b>
                <Flash value={totals.contribution}>{rupeesCompact(totals.contribution)}</Flash>
              </b>
            </span>
          </span>
        </div>
      </section>

      <SelectionOptions
        plan={plan}
        onHover={setHover}
        onUse={(k) => run({ use_option: k }, `${OPT_LABEL[k]} applied · plan recalculated`)}
        editable={edit}
        busy={patch.isPending}
      />

      {/* generate bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-card border border-line bg-surface px-6 py-5">
        <div className="flex flex-col gap-1">
          <b className="text-base">Ready to plan {plural(picked.length, "order")}</b>
          <span className="text-sm text-muted">
            We'll work out sequence, machine and labour load, materials and financials. Steps 2–5
            open once the plan is generated.
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-[13px] text-muted">
            Last generated: {plan.generated_at ? dateTime(plan.generated_at) : "never"}
          </span>
          {plan.status === "draft" ? (
            edit && (
              <Button
                disabled={!picked.length || gen.isPending}
                onClick={async () => {
                  await gen.mutateAsync();
                  go(2);
                }}
              >
                Generate plan →
              </Button>
            )
          ) : (
            <Button variant="dark" onClick={() => go(2)}>
              Next: Proposed sequence →
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

/* ---- order timeline: running orders vs the 3 options ------------------------------------- */

function OrderTimeline({ plan, hover }: { plan: TabProps["plan"]; hover: OptKey }) {
  const sel = plan.result.selection;
  const opts = sel.options;
  const all = [
    ...sel.running.flatMap((r) => [r.start, r.finish]),
    ...(["own", "part", "full"] as OptKey[]).flatMap((k) =>
      Object.values(opts[k]?.rows ?? {}).flatMap((r) => [r.start, r.finish]),
    ),
  ];
  if (!all.length) return null;
  const first = all.reduce((a, b) => (a < b ? a : b));
  const last = all.reduce((a, b) => (a > b ? a : b));
  const days: string[] = [];
  for (
    let d = new Date(`${first}T00:00:00`);
    d <= new Date(`${last}T00:00:00`);
    d.setDate(d.getDate() + 1)
  )
    days.push(
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
    );
  const col = (iso: string) => days.indexOf(iso) + 2;
  const grid = { gridTemplateColumns: `200px repeat(${days.length}, minmax(42px, 1fr))` };
  const runEnd = sel.running.reduce((m, r) => (r.finish > m ? r.finish : m), "");
  const own = new Set(opts.own?.orders ?? []);
  const name = (id: string) => sel.orders[id]?.number ?? "";

  const bar = (cls: string, a: string, b: string, text: string) => (
    <b
      className={cn(
        "z-[1] mx-0.5 flex h-[18px] items-center overflow-hidden rounded-[5px] border px-[7px] text-[10.5px] font-medium whitespace-nowrap",
        cls,
      )}
      style={{ gridColumn: `${col(a)} / ${col(b) + 1}` }}
    >
      {text}
    </b>
  );
  const group = (
    k: OptKey,
    o: SelectionOption | null | undefined,
    tag: { tone: TagTone; text: string },
    sub: string,
  ) =>
    o && (
      <div
        key={k}
        className={cn(
          "relative border-t border-line pb-1.5",
          hover === k && "bg-primary/[0.035] shadow-[inset_3px_0_0_var(--color-primary)]",
        )}
      >
        <div className="flex items-center gap-2.5 px-5 pt-2.5 pb-1">
          <b className="text-sm">{OPT_LABEL[k]}</b>
          <small className="text-xs text-muted">{sub}</small>
          <Tag tone={tag.tone} size="sm">
            {tag.text}
          </Tag>
        </div>
        {o.orders.map((id) => {
          const r = o.rows[id]!;
          return (
            <div key={id} className="grid min-h-7 items-center" style={grid}>
              <span className="sticky left-0 z-[2] flex h-full items-center border-r border-line bg-white pr-3 pl-8 font-mono text-[11.5px] text-ink-3">
                {name(id)}
              </span>
              {bar(
                r.late_days
                  ? "border-hi-line bg-hi-bg text-hi"
                  : own.has(id)
                    ? "border-load-ink/30 bg-load text-load-ink"
                    : "border-ok-line bg-ok-bg text-ok",
                r.start,
                r.finish,
                r.late_days
                  ? `${plural(r.late_days, "day")} late`
                  : own.has(id)
                    ? ""
                    : "Added by optimizer",
              )}
            </div>
          );
        })}
        {k !== "own" &&
          [...own]
            .filter((id) => !o.orders.includes(id))
            .map((id) => (
              <div key={id} className="grid min-h-7 items-center" style={grid}>
                <span className="sticky left-0 z-[2] flex h-full items-center border-r border-line bg-white pr-3 pl-8 font-mono text-[11.5px] text-ink-3">
                  {name(id)}
                </span>
                <span className="col-[2/-1] pl-2 text-[11.5px] text-subtle italic">
                  Left out by the optimizer
                </span>
              </div>
            ))}
      </div>
    );

  return (
    <details className="group overflow-hidden rounded-card border border-line">
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-5 py-4 select-none hover:bg-surface [&::-webkit-details-marker]:hidden">
        <h3 className="m-0 text-[17px] font-semibold">
          <span className="inline-block w-[18px] text-muted transition-transform group-open:rotate-90">
            ▸
          </span>
          Order timeline{" "}
          <small className="ml-1.5 text-[13px] font-normal text-muted">
            Running orders vs. the 3 selection options
          </small>
        </h3>
        <span className="hidden flex-wrap gap-4 text-[13px] text-ink-3 group-open:flex">
          <Legend cls="bg-surface-2 border-faint" text="Running" />
          <Legend cls="bg-load border-load-ink/30" text="Your order" />
          <Legend cls="bg-ok-bg border-ok-line" text="Added by optimizer" />
          <Legend cls="bg-hi-bg border-hi-line" text="Late" />
        </span>
      </summary>
      <div className="relative overflow-x-auto border-t border-divider">
        <div
          className="grid min-h-11 items-center bg-surface text-center text-xs text-ink-2"
          style={grid}
        >
          <span className="sticky left-0 z-[2] h-full border-r border-line bg-surface" />
          {days.map((d) => {
            const p = dayParts(d);
            return (
              <span
                key={d}
                className={cn(
                  "flex flex-col font-semibold",
                  p.sun && "text-subtle",
                  d <= runEnd && "bg-surface-2/60",
                )}
              >
                <small className="text-[10.5px] font-normal text-subtle">{p.dow}</small>
                {p.day}
              </span>
            );
          })}
        </div>
        {sel.running.length > 0 && (
          <div className="border-t border-line pb-1.5">
            <div className="flex items-center gap-2.5 px-5 pt-2.5 pb-1">
              <b className="text-sm">Running now</b>
              <small className="text-xs text-muted">in production or already planned</small>
              <Tag tone="lo" size="sm">
                Locked
              </Tag>
            </div>
            {sel.running.map((r) => (
              <div key={r.id} className="grid min-h-7 items-center" style={grid}>
                <span className="sticky left-0 z-[2] flex h-full items-center border-r border-line bg-white pr-3 pl-8 font-mono text-[11.5px] text-ink-3">
                  {r.number}
                </span>
                {bar(
                  "border-faint bg-surface-2 text-ink-3",
                  r.start,
                  r.finish,
                  `${r.machines[0] ?? ""} · ${r.customer}`,
                )}
              </div>
            ))}
          </div>
        )}
        {group(
          "own",
          opts.own,
          { tone: "bl", text: "Current" },
          opts.own
            ? `${plural(opts.own.orders.length, "order")} · ${range(opts.own.start, opts.own.end)}`
            : "",
        )}
        {group(
          "part",
          opts.part,
          { tone: "md", text: "Keeps your orders" },
          opts.part
            ? `${plural(opts.part.orders.length, "order")} · ${range(opts.part.start, opts.part.end)}`
            : "",
        )}
        {group(
          "full",
          opts.full,
          { tone: "ok", text: "Free choice" },
          opts.full
            ? `${plural(opts.full.orders.length, "order")} · ${range(opts.full.start, opts.full.end)}`
            : "",
        )}
      </div>
      <div className="flex flex-wrap justify-between gap-2 border-t border-divider px-5 py-3 text-[13px] text-muted">
        <span>
          Shaded days: running orders are still on the machines. Hover an option below to highlight
          it here.
        </span>
      </div>
    </details>
  );
}

function Legend({ cls, text }: { cls: string; text: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <i className={cn("inline-block size-3 rounded-[3px] border", cls)} />
      {text}
    </span>
  );
}

/* ---- your selection vs the optimizer -------------------------------------------------------- */

interface Metric {
  label: string;
  get: (o: SelectionOption) => number;
  show: (o: SelectionOption) => string;
  best: "min" | "max";
  key?: boolean;
}

function SelectionOptions({
  plan,
  onHover,
  onUse,
  editable,
  busy,
}: {
  plan: TabProps["plan"];
  onHover: (k: OptKey) => void;
  onUse: (k: Exclude<OptKey, "own">) => void;
  editable: boolean;
  busy: boolean;
}) {
  const sel = plan.result.selection;
  const opts = sel.options;
  const keys: OptKey[] = ["own", "part", "full"];
  const own = new Set(opts.own?.orders ?? []);
  const num = (id: string) => (sel.orders[id]?.number ?? "").replace(/^ORD-/, "");
  const metrics: Metric[] = [
    { label: "Sales value", get: (o) => o.value, show: (o) => rupeesCompact(o.value), best: "max" },
    {
      label: "Production window",
      get: (o) => o.days,
      show: (o) => `${range(o.start, o.end)} · ${plural(o.days, "day")}`,
      best: "min",
    },
    {
      label: "Orders starting alongside running orders",
      get: (o) => o.alongside,
      show: (o) => String(o.alongside),
      best: "max",
    },
    {
      label: "Idle machine-days while running orders run",
      get: (o) => o.idle_days,
      show: (o) => (o.idle_days ? `${o.idle_days} · ${o.idle_machines.join(", ")}` : "0"),
      best: "min",
    },
    {
      label: "Machine utilisation",
      get: (o) => o.utilisation,
      show: (o) => `${o.utilisation}%`,
      best: "max",
    },
    {
      label: "Bottlenecks",
      get: (o) => o.bottlenecks,
      show: (o) =>
        o.bottlenecks ? `${o.bottlenecks} · ${o.bottleneck_names.join(", ").toLowerCase()}` : "0",
      best: "min",
    },
    {
      label: "Late deliveries",
      get: (o) => o.late.length,
      show: (o) =>
        o.late.length
          ? `${o.late.length} · ${o.late.map((i) => sel.orders[i]?.number).join(", ")}`
          : "0",
      best: "min",
    },
    {
      label: "Contribution",
      get: (o) => o.contribution,
      show: (o) => rupeesCompact(o.contribution),
      best: "max",
    },
    {
      label: "Contribution margin",
      get: (o) => o.margin,
      show: (o) => `${o.margin}%`,
      best: "max",
    },
    {
      label: "Contribution per production day",
      get: (o) => o.per_day,
      show: (o) => rupeesCompact(o.per_day),
      best: "max",
      key: true,
    },
  ];
  const present = keys.filter((k) => opts[k]);
  const bestOf = (m: Metric) => {
    const vals = present.map((k) => m.get(opts[k]!));
    const b = m.best === "max" ? Math.max(...vals) : Math.min(...vals);
    return new Set(present.filter((k) => m.get(opts[k]!) === b && vals.some((v) => v !== b)));
  };

  // Plain-language summary, built from the numbers above (no AI maths).
  const summary = (() => {
    const o = opts.own,
      p = opts.part,
      f = opts.full;
    if (!o || !f) return null;
    const out: string[] = [];
    const diff = f.contribution - o.contribution;
    const dropped = [...own].filter((i) => !f.orders.includes(i)).map((i) => sel.orders[i]?.number);
    let full = `Fully optimized earns ${rupeesCompact(Math.abs(diff))} ${diff >= 0 ? "more" : "less"} than your selection`;
    if (f.late.length < o.late.length)
      full += f.late.length ? ", with fewer late deliveries" : ", with no late deliveries";
    if (dropped.length) full += `, but leaves out ${dropped.join(", ")}`;
    out.push(full + ".");
    if (p && p.orders.length > o.orders.length) {
      const pd = p.contribution - o.contribution;
      out.push(
        `Partly optimized keeps all your orders, adds ${p.orders.length - o.orders.length} and earns ${rupeesCompact(Math.abs(pd))} ${pd >= 0 ? "more" : "less"}` +
          (p.late.length ? `; ${plural(p.late.length, "order")} still ships late.` : "."),
      );
    }
    return out.join(" ");
  })();

  return (
    <section className="overflow-hidden rounded-card border border-line">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <h3 className="m-0 text-[17px] font-semibold">
          Order selection options{" "}
          <small className="ml-1.5 text-[13px] font-normal text-muted">
            Your selection vs. what the optimizer suggests
          </small>
        </h3>
        <AssistantBadge>Planning assistant</AssistantBadge>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] border-collapse">
          <thead>
            <tr>
              <th className="w-[240px]" />
              {keys.map((k) => (
                <th
                  key={k}
                  scope="col"
                  onMouseEnter={() => onHover(k)}
                  onFocus={() => onHover(k)}
                  className={cn(
                    "p-4 text-left align-top font-normal normal-case",
                    k === "own" && "bg-surface-blue shadow-[inset_0_3px_0_var(--color-primary)]",
                  )}
                >
                  <div className="mb-1 flex items-center gap-2">
                    <b className="text-[17px] font-semibold">{OPT_LABEL[k]}</b>
                    {k === "own" && (
                      <Tag tone="bl" size="sm">
                        Current
                      </Tag>
                    )}
                  </div>
                  <small className="text-[13px] text-muted">
                    {k === "own"
                      ? "Only the orders you picked"
                      : k === "part"
                        ? "Keeps all your orders, adds what fits"
                        : "Best mix from all accepted orders"}
                  </small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th
                scope="row"
                className="border-t border-divider px-5 py-3 text-left text-[13px] font-medium text-muted"
              >
                Orders
              </th>
              {keys.map((k) => (
                <td key={k} className="border-t border-divider px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {opts[k]?.orders.map((id) => (
                      <span
                        key={id}
                        className={cn(
                          "rounded-md border px-1.5 py-0.5 font-mono text-[11.5px]",
                          own.has(id)
                            ? "border-line-input bg-surface-2 text-ink-2"
                            : "border-ok-line bg-ok-bg text-ok",
                        )}
                      >
                        {own.has(id) ? "" : "+"}
                        {num(id)}
                      </span>
                    ))}
                    {k !== "own" &&
                      [...own]
                        .filter((id) => !opts[k]?.orders.includes(id))
                        .map((id) => (
                          <span
                            key={id}
                            className="rounded-md border border-line-input bg-white px-1.5 py-0.5 font-mono text-[11.5px] text-subtle line-through"
                          >
                            {num(id)}
                          </span>
                        ))}
                  </div>
                </td>
              ))}
            </tr>
            {metrics.map((m) => {
              const best = bestOf(m);
              return (
                <tr key={m.label}>
                  <th
                    scope="row"
                    className={cn(
                      "border-t border-divider px-5 py-3 text-left text-[13px] font-medium whitespace-nowrap text-muted",
                      m.key && "text-[15px] font-semibold text-ink",
                    )}
                  >
                    {m.label}
                  </th>
                  {keys.map((k) => (
                    <td
                      key={k}
                      className={cn(
                        "border-t border-divider px-4 py-3 text-sm",
                        m.key && "text-[15px]",
                      )}
                    >
                      {opts[k] ? (
                        <span
                          className={cn(
                            best.has(k) &&
                              "-ml-2 rounded-md bg-ok-bg px-2 py-0.5 font-semibold text-ok",
                          )}
                        >
                          <Flash value={m.get(opts[k]!)}>{m.show(opts[k]!)}</Flash>
                        </span>
                      ) : (
                        "–"
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
            <tr>
              <th />
              {keys.map((k) => (
                <td key={k} className="border-t border-line px-4 py-4">
                  {k === "own" ? (
                    <Button variant="pill" size="pill" disabled>
                      ✓ Using this
                    </Button>
                  ) : (
                    editable &&
                    opts[k] && (
                      <Button
                        variant="dark"
                        size="sm"
                        disabled={
                          busy ||
                          JSON.stringify([...opts[k]!.orders].sort()) ===
                            JSON.stringify([...own].sort())
                        }
                        onClick={() => onUse(k)}
                      >
                        Use this selection
                      </Button>
                    )
                  )}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {summary && (
        <div className="border-t border-divider px-5 py-3.5 text-sm text-ink-2">{summary}</div>
      )}
      <div className="flex flex-wrap gap-4 border-t border-divider px-5 py-3 text-[13px] text-muted">
        <span>
          <span className="mr-1 inline-block size-2.5 rounded-[3px] border border-ok-line bg-ok-bg align-[-1px]" />{" "}
          Best in row
        </span>
        <span>
          Optimizer: no late deliveries where possible, then the most contribution, then fewer
          bottlenecks.
        </span>
      </div>
    </section>
  );
}
