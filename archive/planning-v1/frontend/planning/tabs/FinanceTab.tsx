import { useState } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { TipRow, Tooltip } from "@/components/ui/Menu";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { rupees, rupeesCompact } from "@/lib/format";
import { usePatchPlan, useRules } from "../api";
import { Flash, RuleButton, type RuleKey } from "../bits";
import { plural } from "../format";
import type { TabProps } from "../PlanningPage";

const PARTS: {
  key: "materials" | "labour" | "machine" | "overheads" | "packaging";
  label: string;
  cls: string;
  rule?: RuleKey;
}[] = [
  { key: "materials", label: "Raw materials", cls: "bg-s1" },
  { key: "labour", label: "Labour", cls: "bg-s2" },
  { key: "machine", label: "Machine / power", cls: "bg-s3" },
  { key: "overheads", label: "Factory overheads", cls: "bg-s4", rule: "overhead" },
  { key: "packaging", label: "Packaging & logistics", cls: "bg-s5", rule: "packaging" },
];

export function FinanceTab({ plan, go }: TabProps) {
  const { can } = useAuth();
  const edit = can("planning.write");
  const fin = plan.result.finance;
  const rows = plan.result.sequence.rows;
  const o = plan.result.selection.orders;
  const rules = useRules().data;
  const patch = usePatchPlan(plan.id);
  const { toast } = useToast();
  const [pendingFixes, setPendingFixes] = useState<string[] | null>(null); // tick shows at once
  const chosenIds = pendingFixes ?? fin.fixes.filter((f) => f.selected).map((f) => f.id);
  const chosen = fin.fixes.filter((f) => chosenIds.includes(f.id));
  const [view, setView] = useState<"before" | "with">("before");
  const f = view === "with" ? fin.with : fin.before;

  const setFixes = async (ids: string[]) => {
    setPendingFixes(ids);
    try {
      const r = await patch.mutateAsync({ fixes: ids });
      setView("with");
      toast({
        title: "Fixes updated · plan recalculated",
        description: `${plural(r.tabs.length, "tab")} changed`,
        tone: "success",
      });
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't apply the fix.",
        tone: "error",
      });
    }
  };
  const lateRows = rows.filter((r) => r.late_days > 0);
  const perDay = rules
    ? rules.penalty_mode === "fixed"
      ? `₹${rupees(rules.penalty_fixed_paise ?? 0)}`
      : `${rules.penalty_percent}% of value`
    : "";
  const saved = fin.before.penalty - fin.with.penalty;
  const fixCost = fin.with.fix_cost;
  const total = f.mfg_cost || 1;

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Financial analysis</h2>
          <p className="m-0 text-sm text-muted">
            What this plan earns, what it costs, and what the planned fixes change.
          </p>
        </div>
        <SegmentedControl
          label="Financial view"
          value={view}
          onChange={setView}
          options={[
            { value: "before", label: "Before fixes" },
            { value: "with", label: `With selected fixes (${chosen.length})` },
          ]}
        />
      </div>

      <dl className="m-0 grid grid-cols-2 overflow-hidden rounded-card border border-line lg:grid-cols-4">
        <Kpi
          label="Total sales value"
          value={f.value}
          sub={plural(rows.length, "selected order")}
        />
        <Kpi
          label="Manufacturing cost"
          value={f.cost}
          sub={f.fix_cost ? `Incl. ${rupeesCompact(f.fix_cost)} in fixes` : "Estimated cost"}
        />
        <Kpi
          label="Expected contribution"
          value={f.contribution}
          sub={
            f.penalty
              ? `After ${rupeesCompact(f.penalty)} penalty at risk`
              : "No penalties · all on time"
          }
        />
        <Kpi
          label="Contribution margin"
          value={f.margin}
          pct
          sub="Before fixed corporate costs and tax"
        />
      </dl>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="flex flex-col gap-3.5 rounded-card border border-line p-5">
          <div className="flex items-baseline justify-between">
            <h3 className="m-0 text-[17px] font-semibold">Cost breakdown</h3>
            <span className="text-sm text-muted">
              Total{" "}
              <b className="text-ink">
                <Flash value={f.mfg_cost}>{rupeesCompact(f.mfg_cost)}</Flash>
              </b>
            </span>
          </div>
          <div
            className="flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-divider"
            role="img"
            aria-label="Cost breakdown"
          >
            {PARTS.filter((p) => f.breakdown[p.key] > 0).map((p) => (
              <Tooltip
                key={p.key}
                content={
                  <div className="w-[200px]">
                    <TipRow
                      label={p.label}
                      value={`${rupeesCompact(f.breakdown[p.key])} · ${((100 * f.breakdown[p.key]) / total).toFixed(1)}%`}
                    />
                  </div>
                }
              >
                <i
                  tabIndex={0}
                  className={cn("block h-full", p.cls)}
                  style={{ width: `${(100 * f.breakdown[p.key]) / total}%` }}
                />
              </Tooltip>
            ))}
          </div>
          <div>
            {PARTS.map((p) => (
              <div
                key={p.key}
                className="flex items-center justify-between border-t border-divider py-2.5 text-sm"
              >
                <span className="flex items-center gap-2.5">
                  <i className={cn("inline-block size-2.5 rounded-[3px]", p.cls)} />
                  {p.label}
                  {p.rule && <RuleButton rule={p.rule} />}
                </span>
                <span className="flex items-baseline gap-3">
                  <b>
                    <Flash value={f.breakdown[p.key]}>{rupeesCompact(f.breakdown[p.key])}</Flash>
                  </b>
                  <small className="w-11 text-right text-xs text-subtle">
                    {((100 * f.breakdown[p.key]) / total).toFixed(1)}%
                  </small>
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-3.5 rounded-card border border-line p-5">
          <h3 className="m-0 text-[17px] font-semibold">Plan adjustments</h3>
          <div className="text-[13px]">
            <Line
              label="Base contribution"
              value={rupeesCompact(f.base_contribution)}
              raw={f.base_contribution}
            />
            <Line
              label={
                <span className="flex flex-col">
                  <span className="flex items-center gap-1.5">
                    Late-delivery penalty at risk <RuleButton rule="penalty" />
                  </span>
                  <small className="text-xs text-subtle">
                    {lateRows.length
                      ? lateRows
                          .map(
                            (r) => `${o[r.id]?.number} · ${plural(r.late_days, "day")} × ${perDay}`,
                          )
                          .join("; ")
                      : "No late deliveries"}
                    {view === "with" && saved > 0 ? " · avoided by the fixes" : ""}
                  </small>
                </span>
              }
              value={f.penalty ? `−${rupeesCompact(f.penalty)}` : "₹0"}
              raw={f.penalty}
            />
            {fin.fixes.map((x) => (
              <div
                key={x.id}
                className="flex items-center justify-between gap-3 border-t border-divider py-2"
              >
                <label className="flex cursor-pointer items-start gap-2 text-muted">
                  <input
                    type="checkbox"
                    className="mt-0.5 accent-primary"
                    checked={chosenIds.includes(x.id)}
                    disabled={!edit || patch.isPending}
                    onChange={(e) =>
                      setFixes(
                        e.target.checked
                          ? [...chosen.map((c) => c.id), x.id]
                          : chosen.filter((c) => c.id !== x.id).map((c) => c.id),
                      )
                    }
                  />
                  <span className="flex flex-col">
                    <span className="text-ink-2">{x.label}</span>
                    <small className="text-xs text-subtle">
                      {x.solves.length ? `Fixes: ${x.solves.join("; ")}` : "Chosen fix"}
                      {x.penalty_avoided
                        ? ` · avoids ${rupeesCompact(x.penalty_avoided)} penalty`
                        : ""}
                    </small>
                  </span>
                </label>
                <b>{view === "with" && x.selected ? `−${rupeesCompact(x.cost)}` : "–"}</b>
              </div>
            ))}
            <Line
              label={<b className="text-ink">Expected contribution</b>}
              value={rupeesCompact(f.contribution)}
              raw={f.contribution}
              strong
            />
          </div>
          {chosen.length > 0 && (
            <div className="rounded-xl bg-surface px-3.5 py-2.5 text-[13px] text-ink-2">
              {fixCost > saved ? (
                <>
                  The fixes cost <b>{rupeesCompact(fixCost - saved)} more</b> than the penalty they
                  avoid
                </>
              ) : (
                <>
                  The fixes cost <b>{rupeesCompact(saved - fixCost)} less</b> than the penalty they
                  avoid
                </>
              )}
              {fin.with.penalty === 0 ? ", and every order ships on time." : "."}
            </div>
          )}
          {fin.fixes.length === 0 && (
            <p className="m-0 text-[13px] text-muted">No fixes needed: nothing is late or short.</p>
          )}
        </section>
      </div>

      <section className="overflow-hidden rounded-card border border-line">
        <div className="px-5 py-4">
          <h3 className="m-0 text-[17px] font-semibold">Profit by order</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="bg-surface">
              <tr className="text-left text-xs font-semibold tracking-[0.04em] text-muted uppercase">
                <th className="px-4 py-3">Order</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3 text-right">Value</th>
                <th className="px-4 py-3 text-right">Mfg. cost</th>
                <th className="px-4 py-3 text-right">Penalty risk</th>
                <th className="px-4 py-3 text-right">Fix cost</th>
                <th className="px-4 py-3 text-right">Contribution</th>
                <th className="px-4 py-3">Margin</th>
              </tr>
            </thead>
            <tbody>
              {f.rows.map((r) => (
                <tr key={r.id} className="border-t border-divider">
                  <td className="px-4 py-3.5 font-mono">{o[r.id]?.number}</td>
                  <td className="px-4 py-3.5">{o[r.id]?.customer}</td>
                  <td className="px-4 py-3.5 text-right">{rupeesCompact(r.value)}</td>
                  <td className="px-4 py-3.5 text-right">{rupeesCompact(r.cost)}</td>
                  <td className="px-4 py-3.5 text-right">
                    {r.penalty ? rupeesCompact(r.penalty) : "–"}
                  </td>
                  <td className="px-4 py-3.5 text-right">
                    {r.fix_cost ? rupeesCompact(r.fix_cost) : "–"}
                  </td>
                  <td className="px-4 py-3.5 text-right font-semibold">
                    <Flash value={r.contribution}>{rupeesCompact(r.contribution)}</Flash>
                  </td>
                  <td className="px-4 py-3.5 whitespace-nowrap">
                    <span className="mr-2 inline-block h-1.5 w-[90px] overflow-hidden rounded-full bg-divider align-middle">
                      <i
                        className="block h-full rounded-full bg-primary"
                        style={{ width: `${Math.max(0, Math.min(100, r.margin * 2.5))}%` }}
                      />
                    </span>
                    <Flash value={r.margin}>{r.margin.toFixed(1)}%</Flash>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap justify-between gap-3 border-t border-line bg-surface px-5 py-3.5 text-sm">
          <span className="text-muted">Total for {plural(f.rows.length, "order")}</span>
          <span className="flex flex-wrap gap-6">
            <span>
              Value <b>{rupeesCompact(f.value)}</b>
            </span>
            <span>
              Cost <b>{rupeesCompact(f.cost)}</b>
            </span>
            <span>
              Contribution <b>{rupeesCompact(f.contribution)}</b>
            </span>
            <span>
              Margin <b>{f.margin.toFixed(1)}%</b>
            </span>
          </span>
        </div>
      </section>

      <div className="flex justify-between">
        <Button variant="pill" onClick={() => go(3)}>
          ← Production schedule
        </Button>
        <Button variant="dark" onClick={() => go(5)}>
          Next: Final plan approval →
        </Button>
      </div>
    </section>
  );
}

function Kpi({
  label,
  value,
  sub,
  pct,
}: {
  label: string;
  value: number;
  sub: string;
  pct?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1 border-line px-[22px] py-[18px] [&+&]:border-l">
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className="m-0 text-[28px] font-bold tracking-[-0.01em]">
        <Flash value={value}>{pct ? `${value.toFixed(1)}%` : rupeesCompact(value)}</Flash>
      </dd>
      <small className="text-xs text-subtle">{sub}</small>
    </div>
  );
}

function Line({
  label,
  value,
  raw,
  strong,
}: {
  label: React.ReactNode;
  value: string;
  raw: number;
  strong?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-t border-divider py-2 first:border-t-0",
        strong && "text-sm",
      )}
    >
      <span className="text-muted">{label}</span>
      <b>
        <Flash value={raw}>{value}</Flash>
      </b>
    </div>
  );
}
