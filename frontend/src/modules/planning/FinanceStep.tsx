import { createColumnHelper } from "@tanstack/react-table";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { rupees, rupeesCompact } from "@/lib/format";
import { usePatchPlan, type Finance, type Plan } from "./api";
import { Flash } from "./Flash";
import { plural } from "./format";
import { RuleButton, type RuleKey } from "./RuleButton";

type View = "before" | "with";
type Row = Finance["rows"][number];

// One hue, five steps (dataviz: a part-to-whole of one measure).
const SHADES = ["bg-primary", "bg-primary/70", "bg-primary/45", "bg-primary/25", "bg-primary/12"];
const COST_PARTS: { key: keyof Finance["breakdown"]; label: string; rule?: RuleKey }[] = [
  { key: "materials", label: "Raw materials" },
  { key: "labour", label: "Labour" },
  { key: "machine", label: "Machine / power" },
  { key: "overheads", label: "Factory overheads", rule: "overhead" },
  { key: "packaging", label: "Packaging & logistics", rule: "packaging" },
];

/** "₹24.15 L" (two decimals for lakhs, like the mockup) / "₹20,000". */
function money(paise: number): string {
  const abs = Math.abs(paise) / 100;
  const sign = paise < 0 ? "−" : "";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
  return `${sign}₹${rupees(Math.abs(paise))}`;
}

/** Step 4: what this plan earns, what it costs, and what the planned fixes change. */
export function FinanceStep({ plan, go }: { plan: Plan; go: (step: string) => void }) {
  const { can } = useAuth();
  const edit = can("planning.write") && plan.status !== "approved";
  const fin = plan.result.finance;
  const orders = plan.result.selection.orders;
  const num = (id: string) => orders[id]?.number ?? id;
  const chosen = fin.fixes.filter((f) => f.selected);
  const [view, setView] = useState<View>(chosen.length ? "with" : "before");
  const v = view === "with" ? fin.with : fin.before;
  const patch = usePatchPlan(plan.id);
  const { toast } = useToast();
  const lateNow = plan.result.sequence.overview.late ?? 0;
  // show the tick at once while the plan recalculates
  const [pending, setPending] = useState<Record<string, boolean>>({});

  const tick = async (id: string, on: boolean) => {
    const next = on
      ? [...chosen.map((f) => f.id), id]
      : chosen.map((f) => f.id).filter((x) => x !== id);
    setPending({ [id]: on });
    try {
      const r = await patch.mutateAsync({ fixes: next });
      setView(next.length ? "with" : "before");
      toast({
        title: on ? "Fix added to the plan" : "Fix removed from the plan",
        description: r.tabs.length ? `${plural(r.tabs.length, "step")} updated` : undefined,
        tone: "success",
      });
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't change the fixes.",
        tone: "error",
      });
    } finally {
      setPending({});
    }
  };

  const perDay = (r: Row) =>
    fin.before.penalty_rule?.mode === "percent"
      ? `${fin.before.penalty_rule.value}% of value`
      : money(r.late_days ? r.penalty / r.late_days : 0);
  const lateRows = v.rows.filter((r) => r.penalty > 0);

  // the insight line: fix cost vs penalty avoided, recalculated every time
  const avoided = fin.before.penalty - fin.with.penalty;
  const extra = fin.with.fix_cost - avoided;
  const insight = !chosen.length
    ? fin.fixes.length
      ? "No fixes chosen yet. Tick one to apply it to the plan; steps 2 and 3 update with it."
      : lateNow
        ? "No night shift or express material would fix this plan."
        : "No fixes needed: every order ships on time."
    : `The fixes cost ${money(Math.abs(extra))} ${extra > 0 ? "more" : "less"} than the penalty they avoid` +
      (lateNow
        ? `, and ${plural(lateNow, "order")} still ${lateNow === 1 ? "ships" : "ship"} late.`
        : ", and every order ships on time.");

  const marginTone = (m: number) =>
    m < fin.before.min_margin ? "bg-hi" : m >= fin.before.min_margin + 5 ? "bg-ok" : "bg-primary";

  const col = createColumnHelper<Row>();
  const columns = [
    col.accessor((r) => num(r.id), {
      id: "order",
      header: "Order",
      meta: { label: "Order", mono: true, alwaysVisible: true },
      cell: (c) => <b className="font-mono font-semibold">{c.getValue()}</b>,
    }),
    col.accessor((r) => orders[r.id]?.customer ?? "", {
      id: "customer",
      header: "Customer",
      meta: { label: "Customer" },
    }),
    col.accessor("value", {
      id: "value",
      header: "Value",
      meta: { label: "Value", align: "right" },
      cell: (c) => rupeesCompact(c.getValue()),
    }),
    col.accessor("cost", {
      id: "cost",
      header: "Mfg. cost",
      meta: { label: "Mfg. cost", align: "right" },
      cell: (c) => money(c.getValue()),
    }),
    col.accessor("penalty", {
      id: "penalty",
      header: "Penalty risk",
      meta: { label: "Penalty risk", align: "right" },
      cell: (c) => (c.getValue() ? <Flash value={c.getValue()}>{money(c.getValue())}</Flash> : "–"),
    }),
    col.accessor("fix_cost", {
      id: "fix_cost",
      header: "Fix cost",
      meta: { label: "Fix cost", align: "right" },
      cell: (c) => (c.getValue() ? <Flash value={c.getValue()}>{money(c.getValue())}</Flash> : "–"),
    }),
    col.accessor("contribution", {
      id: "contribution",
      header: "Contribution",
      meta: { label: "Contribution", align: "right" },
      cell: (c) => (
        <b>
          <Flash value={c.getValue()}>{money(c.getValue())}</Flash>
        </b>
      ),
    }),
    col.accessor("margin", {
      id: "margin",
      header: "Margin",
      meta: { label: "Margin" },
      cell: (c) => {
        const m = c.getValue();
        return (
          <span className="flex items-center gap-3">
            <span
              className="block h-1.5 w-[70px] overflow-hidden rounded-full bg-divider"
              aria-hidden
            >
              <span
                className={cn("block h-full rounded-full", marginTone(m))}
                style={{ width: `${Math.max(0, Math.min(100, m * 3))}%` }}
              />
            </span>
            <Flash value={m}>{m.toFixed(1)}%</Flash>
          </span>
        );
      },
    }),
  ];

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Financial analysis</h2>
          <p className="m-0 text-[15px] text-muted">
            What this plan earns, what it costs, and what the planned fixes change.
          </p>
        </div>
        <SegmentedControl<View>
          label="Show numbers"
          value={view}
          onChange={setView}
          options={[
            { value: "before", label: "Before fixes" },
            { value: "with", label: `With selected fixes (${chosen.length})` },
          ]}
        />
      </div>

      {/* overview */}
      <div className="grid overflow-hidden rounded-card border border-line bg-surface sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Total sales value"
          value={rupeesCompact(v.value)}
          note={`${plural(v.rows.length, "selected order")}`}
        />
        <Kpi
          label="Manufacturing cost"
          value={money(v.cost)}
          note={v.fix_cost ? `Incl. ${money(v.fix_cost)} in fixes` : "Estimated cost"}
        />
        <Kpi
          label="Expected contribution"
          value={money(v.contribution)}
          tone={v.contribution >= 0 ? "ok" : "hi"}
          note={
            v.penalty
              ? `After ${money(v.penalty)} penalty at risk`
              : view === "with" && chosen.length
                ? "No penalties · all on time"
                : "No penalties at risk"
          }
        />
        <Kpi
          label="Contribution margin"
          value={`${v.margin.toFixed(1)}%`}
          tone={v.margin < v.min_margin ? "hi" : undefined}
          note={
            <span className="inline-flex items-center gap-1">
              {v.margin < v.min_margin
                ? `Below your ${v.min_margin}% minimum`
                : "Before fixed corporate costs and tax"}
              <RuleButton rule="min_margin" />
            </span>
          }
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        {/* cost breakdown */}
        <section
          aria-label="Cost breakdown"
          className="flex flex-col gap-4 rounded-card border border-line p-[22px]"
        >
          <div className="flex items-center justify-between">
            <h3 className="m-0 text-[17px] font-semibold">Cost breakdown</h3>
            <span className="text-sm text-muted">
              Total <b className="text-ink">{money(v.cost)}</b>
            </span>
          </div>
          <CostBar fin={v} />
          <div className="flex flex-col">
            {[
              ...COST_PARTS.map((p, i) => ({
                ...p,
                amount: v.breakdown[p.key],
                shade: SHADES[i]!,
              })),
              ...(v.fix_cost
                ? [
                    {
                      key: "fixes",
                      label: "Plan fixes",
                      rule: undefined,
                      amount: v.fix_cost,
                      shade: "bg-md-accent",
                    },
                  ]
                : []),
            ].map((p) => (
              <div
                key={p.key}
                className="flex items-center justify-between gap-3 border-t border-divider py-2.5 text-sm"
              >
                <span className="flex items-center gap-2.5">
                  <i className={cn("inline-block size-2.5 rounded-[3px]", p.shade)} aria-hidden />
                  {p.label}
                  {p.rule && <RuleButton rule={p.rule} />}
                </span>
                <span className="flex items-baseline gap-3">
                  <b>
                    <Flash value={p.amount}>{money(p.amount)}</Flash>
                  </b>
                  <small className="w-12 text-right text-xs text-subtle">
                    {v.cost ? ((100 * p.amount) / v.cost).toFixed(1) : "0.0"}%
                  </small>
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* plan adjustments */}
        <section
          aria-label="Plan adjustments"
          className="flex flex-col gap-3 rounded-card border border-line p-[22px]"
        >
          <h3 className="m-0 text-[17px] font-semibold">Plan adjustments</h3>
          <div className="flex flex-col text-sm">
            <Line label="Base contribution" value={<b>{money(v.base_contribution)}</b>} />
            <Line
              label={
                <span className="flex flex-col">
                  <span className="inline-flex items-center gap-1">
                    Late-delivery penalty at risk <RuleButton rule="penalty" />
                  </span>
                  {lateRows.map((r) => (
                    <small key={r.id} className="text-xs text-subtle">
                      {num(r.id)} · {plural(r.late_days, "day")} × {perDay(r)}
                    </small>
                  ))}
                </span>
              }
              value={
                <b className={cn(v.penalty && "text-hi")}>
                  <Flash value={v.penalty}>{v.penalty ? `−${money(v.penalty)}` : "₹0"}</Flash>
                </b>
              }
            />
            {fin.fixes.map((f) => (
              <Line
                key={f.id}
                label={
                  <label className={cn("flex items-start gap-2.5", edit && "cursor-pointer")}>
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={pending[f.id] ?? f.selected}
                      disabled={!edit || patch.isPending}
                      onChange={(e) => void tick(f.id, e.target.checked)}
                      aria-label={`Apply ${f.label}`}
                    />
                    <span className="flex flex-col">
                      <span>{f.label}</span>
                      <small className="text-xs text-subtle">
                        {money(f.cost)}
                        {f.solves.length ? ` · fixes ${f.solves.join(", ")}` : ""}
                        {f.penalty_avoided ? ` · avoids ${money(f.penalty_avoided)} penalty` : ""}
                      </small>
                    </span>
                  </label>
                }
                value={<b>{view === "with" && f.selected ? `−${money(f.cost)}` : "–"}</b>}
              />
            ))}
            <Line
              strong
              label="Expected contribution"
              value={
                <b className="text-ok">
                  <Flash value={v.contribution}>{money(v.contribution)}</Flash>
                </b>
              }
            />
          </div>
          <div
            className={cn(
              "rounded-xl px-4 py-3 text-[13px]",
              chosen.length && extra > 0 ? "bg-md-bg text-md" : "bg-surface text-ink-2",
            )}
          >
            {insight}
          </div>
        </section>
      </div>

      {/* profit by order */}
      <div className="flex flex-col">
        <DataTable<Row>
          tableId="planning-profit"
          title="Profit by order"
          columns={columns}
          data={v.rows}
          getRowId={(r) => r.id}
          maxHeight={10_000}
        />
        <div className="-mt-px flex flex-wrap items-center justify-between gap-3 rounded-b-card border border-line bg-surface px-5 py-3.5 text-sm text-muted">
          <span>Total for {plural(v.rows.length, "order")}</span>
          <span className="flex flex-wrap gap-6">
            <span>
              Value <b className="text-ink">{rupeesCompact(v.value)}</b>
            </span>
            <span>
              Cost <b className="text-ink">{money(v.cost)}</b>
            </span>
            <span>
              Contribution <b className="text-ok">{money(v.contribution)}</b>
            </span>
            <span>
              Margin <b className="text-ink">{v.margin.toFixed(1)}%</b>
            </span>
          </span>
        </div>
      </div>

      <div className="flex flex-wrap justify-between gap-3">
        <Button variant="pill" onClick={() => go("3")}>
          ← Production schedule
        </Button>
        <Button variant="dark" onClick={() => go("5")}>
          Next: Final plan approval →
        </Button>
      </div>
    </section>
  );
}

function Kpi({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: ReactNode;
  tone?: "ok" | "hi";
}) {
  return (
    <div className="flex flex-col gap-1 border-line px-[22px] py-5 not-first:border-t sm:not-first:border-t-0 sm:[&:nth-child(n+2)]:border-l">
      <span className="text-[13px] text-muted">{label}</span>
      <b
        className={cn(
          "text-[28px] leading-tight font-bold",
          tone === "ok" && "text-ok",
          tone === "hi" && "text-hi",
        )}
      >
        <Flash value={value} />
      </b>
      <small className="text-xs text-subtle">{note}</small>
    </div>
  );
}

function Line({ label, value, strong }: { label: ReactNode; value: ReactNode; strong?: boolean }) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-3 border-t border-divider py-3",
        strong && "font-semibold",
      )}
    >
      <span className="text-ink-2">{label}</span>
      <span className="whitespace-nowrap">{value}</span>
    </div>
  );
}

function CostBar({ fin }: { fin: Finance }) {
  const parts = [
    ...COST_PARTS.map((p, i) => ({
      label: p.label,
      amount: fin.breakdown[p.key],
      shade: SHADES[i]!,
    })),
    ...(fin.fix_cost ? [{ label: "Plan fixes", amount: fin.fix_cost, shade: "bg-md-accent" }] : []),
  ];
  return (
    <div
      className="flex h-2.5 gap-0.5 overflow-hidden rounded-full"
      role="img"
      aria-label="Cost split"
    >
      {parts
        .filter((p) => p.amount > 0)
        .map((p) => (
          <i
            key={p.label}
            title={`${p.label}: ${money(p.amount)}`}
            className={cn("block h-full", p.shade)}
            style={{ width: `${(100 * p.amount) / (fin.cost || 1)}%` }}
          />
        ))}
    </div>
  );
}
