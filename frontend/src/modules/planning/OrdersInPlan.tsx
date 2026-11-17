import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { count, rupeesCompact, shortDate } from "@/lib/format";
import type { Selection } from "./api";
import { plural } from "./format";

const PRI_TONE: Record<string, TagTone> = { high: "hi", medium: "md", low: "lo" };
const PRI_LABEL: Record<string, string> = { high: "High", medium: "Medium", low: "Low" };

/**
 * "In this plan": every accepted order. Ticked = in the plan (and "In planning" in Orders received).
 * Unticked orders show "Suggested" when an optimizer option uses them, else "Excluded".
 */
export function OrdersInPlan({
  selection,
  ticked,
  editable,
  busy,
  onToggle,
}: {
  selection: Selection;
  ticked: string[];
  editable: boolean;
  busy: boolean;
  onToggle: (id: string, on: boolean) => void;
}) {
  const [sort, setSort] = useState<"deadline" | "value" | "margin">("deadline");
  const on = useMemo(() => new Set(ticked), [ticked]);
  const opts = selection.options;
  const suggested = new Set([...(opts.part?.orders ?? []), ...(opts.full?.orders ?? [])]);
  const rows = useMemo(() => {
    const all = Object.entries(selection.orders).map(([id, o]) => ({ id, ...o }));
    const by = {
      deadline: (a: (typeof all)[number], b: (typeof all)[number]) =>
        a.deadline.localeCompare(b.deadline),
      value: (a: (typeof all)[number], b: (typeof all)[number]) => b.value - a.value,
      margin: (a: (typeof all)[number], b: (typeof all)[number]) => b.est_margin - a.est_margin,
    }[sort];
    // Ticked orders first; the rest at the bottom (muted, Suggested / Excluded), as in the mockup.
    return all.sort(
      (a, b) =>
        Number(on.has(b.id)) - Number(on.has(a.id)) || by(a, b) || a.number.localeCompare(b.number),
    );
  }, [selection.orders, sort, on]);
  const picked = rows.filter((r) => on.has(r.id));
  const inUse = selection.using ? opts[selection.using] : null;

  return (
    <section className="overflow-hidden rounded-card border border-line">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <h3 className="m-0 text-[17px] font-semibold">In this plan</h3>
          <Tag tone="lo">
            {picked.length} of {rows.length}
          </Tag>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Sort orders"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
            className="cursor-pointer rounded-full border border-line-input bg-card px-3.5 py-2 text-[13px] font-medium text-ink-2"
          >
            <option value="deadline">Sort: Deadline</option>
            <option value="value">Sort: Value</option>
            <option value="margin">Sort: Est. margin</option>
          </select>
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
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={10}
                  className="border-t border-divider px-5 py-8 text-center text-sm text-muted"
                >
                  No accepted orders yet. Accept orders in Orders received, or send them to
                  Planning.
                </td>
              </tr>
            )}
            {rows.map((r) => {
              const ticked = on.has(r.id);
              return (
                <tr
                  key={r.id}
                  className={cn("border-t border-divider text-sm", !ticked && "text-subtle")}
                >
                  <td className="px-4 py-3.5">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={ticked}
                      disabled={!editable || busy}
                      aria-label={`Include ${r.number}`}
                      onChange={(e) => onToggle(r.id, e.target.checked)}
                    />
                  </td>
                  <td className="px-4 py-3.5 font-mono">{r.number}</td>
                  <td className="px-4 py-3.5">{r.customer}</td>
                  <td className="px-4 py-3.5">{r.product}</td>
                  <td className={cn("px-4 py-3.5", !ticked && "opacity-55")}>
                    <Tag tone={PRI_TONE[r.priority] ?? "lo"}>
                      {PRI_LABEL[r.priority] ?? r.priority}
                    </Tag>
                  </td>
                  <td className="px-4 py-3.5 text-right whitespace-nowrap">
                    {count(r.qty)} {r.unit}
                  </td>
                  <td className="px-4 py-3.5 text-right">{rupeesCompact(r.value)}</td>
                  <td className="px-4 py-3.5 whitespace-nowrap">{shortDate(r.deadline)}</td>
                  <td className="px-4 py-3.5 text-right">{r.est_margin}%</td>
                  <td className="px-4 py-3.5 text-right">
                    {ticked ? (
                      editable && (
                        <button
                          type="button"
                          aria-label={`Remove ${r.number}`}
                          disabled={busy}
                          onClick={() => onToggle(r.id, false)}
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
            Qty <b>{count(picked.reduce((s, r) => s + r.qty, 0))} pcs</b>
          </span>
          <span>
            Value <b>{rupeesCompact(picked.reduce((s, r) => s + r.value, 0))}</b>
          </span>
          <span>
            Est. contribution <b>{inUse ? rupeesCompact(inUse.contribution) : "–"}</b>
          </span>
        </span>
      </div>
    </section>
  );
}
