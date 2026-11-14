import { useState } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { dateTime, rupeesCompact, shortDate } from "@/lib/format";
import { useApprove, useHistory, useRaisePo } from "../api";
import { Flash, RuleButton } from "../bits";
import { plural, range } from "../format";
import type { TabProps } from "../PlanningPage";

export function ApprovalTab({ plan, go }: TabProps) {
  const { can } = useAuth();
  const r = plan.result;
  const o = r.selection.orders;
  const fin = r.finance.with;
  const ov = r.sequence.overview;
  const approve = useApprove(plan.id);
  const raise = useRaisePo(plan.id);
  const history = useHistory(plan.id, plan.version);
  const { toast } = useToast();
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const open = r.purchase_needs.filter((n) => !n.requested);
  const approved = plan.status === "approved" && !plan.needs_reapproval;

  const doApprove = async (raiseOpen: boolean) => {
    try {
      await approve.mutateAsync({ note: note || null, raise_open_pos: raiseOpen });
      setConfirm(false);
      toast({
        title: "Plan approved",
        description: "Promised dates are on the orders; purchase requests are recorded.",
        tone: "success",
      });
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't approve the plan.",
        tone: "error",
      });
    }
  };
  const raisePo = async (material: string) => {
    try {
      await raise.mutateAsync(material);
      toast({ title: "PO requested", description: "Recorded for Purchasing.", tone: "success" });
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't request the PO.",
        tone: "error",
      });
    }
  };

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Final plan approval</h2>
          <p className="m-0 text-sm text-muted">
            Check the final order combination and schedule, then approve it to send it to Purchasing
            and Production.
          </p>
        </div>
        {approved ? <Tag tone="ok">Approved</Tag> : <Tag tone="md">Awaiting owner approval</Tag>}
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.75fr)_minmax(320px,1fr)]">
        <div className="flex flex-col gap-5">
          <section className="overflow-hidden rounded-card border border-line">
            <div className="flex items-center justify-between gap-3 px-5 py-[18px]">
              <h3 className="m-0 text-[17px] font-semibold">
                {plan.number}{" "}
                <small className="ml-1.5 text-[13px] font-normal text-muted">
                  {range(ov.start, ov.end)} · {fin.fixes.length} fix
                  {fin.fixes.length === 1 ? "" : "es"} applied
                </small>
              </h3>
              <button
                type="button"
                className="cursor-pointer border-0 bg-transparent text-[13px] text-link"
                onClick={() => go(3)}
              >
                View schedule →
              </button>
            </div>
            <dl className="m-0 grid grid-cols-2 border-t border-divider sm:grid-cols-5">
              {[
                ["Orders", ov.orders, String(ov.orders)],
                ["Production days", ov.days, String(ov.days)],
                ["Sales value", fin.value, rupeesCompact(fin.value)],
                ["Contribution", fin.contribution, rupeesCompact(fin.contribution)],
                ["Margin", fin.margin, `${fin.margin.toFixed(1)}%`],
              ].map(([label, raw, text]) => (
                <div
                  key={String(label)}
                  className="flex flex-col gap-1 border-line px-5 py-4 [&+&]:border-l"
                >
                  <dt className="text-[13px] text-muted">{label}</dt>
                  <dd className="m-0 text-2xl font-bold">
                    <Flash value={raw}>{text}</Flash>
                  </dd>
                </div>
              ))}
            </dl>
            <table className="w-full border-collapse text-sm">
              <thead className="bg-surface">
                <tr className="text-left text-xs font-semibold tracking-[0.04em] text-muted uppercase">
                  <th className="px-4 py-3">Order</th>
                  <th className="px-4 py-3">Customer</th>
                  <th className="px-4 py-3">Finishes</th>
                  <th className="px-4 py-3">Deadline</th>
                  <th className="px-4 py-3">Delivery</th>
                </tr>
              </thead>
              <tbody>
                {r.sequence.rows.map((s) => (
                  <tr key={s.id} className="border-t border-divider">
                    <td className="px-4 py-3 font-mono">{o[s.id]?.number}</td>
                    <td className="px-4 py-3">{o[s.id]?.customer}</td>
                    <td className="px-4 py-3">
                      <Flash value={s.finish}>{shortDate(s.finish)}</Flash>
                    </td>
                    <td className="px-4 py-3">{shortDate(s.deadline)}</td>
                    <td className="px-4 py-3">
                      {s.late_days ? (
                        <Tag tone="hi">Late · {plural(s.late_days, "day")}</Tag>
                      ) : (
                        <Tag tone="ok">On time</Tag>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {fin.fixes.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-divider px-5 py-3.5 text-[13px] text-muted">
                Fixes applied:
                {fin.fixes.map((x) => (
                  <span
                    key={x.id}
                    className="rounded-md border border-line-input bg-surface-2 px-2 py-0.5 font-mono text-xs text-ink-2"
                  >
                    {x.label} · {rupeesCompact(x.cost)}
                  </span>
                ))}
              </div>
            )}
          </section>

          <section className="overflow-hidden rounded-card border border-line">
            <div className="flex items-center justify-between gap-3 px-5 py-[18px]">
              <h3 className="m-0 text-[17px] font-semibold">Readiness checklist</h3>
              <Tag tone={r.approval.ready === r.approval.total ? "ok" : "md"}>
                {r.approval.ready} of {r.approval.total} ready
              </Tag>
            </div>
            <div className="px-5 pb-2">
              {r.approval.checks.map((c) => (
                <div
                  key={c.title}
                  className="flex items-center gap-3 border-t border-divider py-3.5 first:border-t-0"
                >
                  <span
                    className={cn(
                      "grid size-[26px] flex-none place-items-center rounded-full text-[13px] font-bold",
                      c.ok ? "bg-ok-bg text-ok" : "bg-md-bg text-md",
                    )}
                  >
                    {c.ok ? "✓" : "!"}
                  </span>
                  <div className="flex-1">
                    <b className="flex items-center gap-1.5 text-sm font-semibold">
                      {c.title}
                      {c.setting === "min_margin_pct" && <RuleButton rule="min_margin" />}
                    </b>
                    {c.text && <small className="text-[13px] text-muted">{c.text}</small>}
                  </div>
                  {c.action === "raise_po" &&
                    can("planning.write") &&
                    open.map((n) => (
                      <Button
                        key={n.material}
                        variant="pill"
                        size="pill"
                        disabled={raise.isPending}
                        onClick={() => raisePo(n.material)}
                      >
                        Raise PO now · {n.name}
                      </Button>
                    ))}
                </div>
              ))}
            </div>
            {r.purchase_needs.length > 0 && (
              <div className="border-t border-divider px-5 py-3.5 text-[13px] text-muted">
                <b className="text-ink-2">Purchase requests</b>
                <ul className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0">
                  {r.purchase_needs.map((n) => (
                    <li key={n.material}>
                      {n.qty} {n.unit} {n.name} by {shortDate(n.needed_by)} for{" "}
                      {n.orders.join(", ")}
                      {n.express ? " · express" : ""} ·{" "}
                      <span className={n.requested ? "text-ok" : "text-md"}>
                        {n.requested ? "requested" : "not raised yet"}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="m-0 mt-1.5 text-xs">
                  Requests are recorded now and picked up by Purchasing when that module is built.
                </p>
              </div>
            )}
          </section>
        </div>

        <aside className="flex flex-col gap-[18px] rounded-card border border-line bg-white p-5 xl:sticky xl:top-5">
          <h3 className="m-0 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
            Owner approval
          </h3>
          {approved ? (
            <p className="m-0 text-sm">
              Approved {plan.approved_at ? dateTime(plan.approved_at) : ""}.
              {plan.approval_note && (
                <span className="block text-muted">“{plan.approval_note}”</span>
              )}
            </p>
          ) : can("planning.approve") ? (
            <>
              <label className="flex flex-col gap-1.5 text-[13px] font-medium text-ink-2">
                <span>
                  Note <span className="font-normal text-muted">(optional)</span>
                </span>
                <textarea
                  rows={3}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. Confirm night-shift crew with the supervisor"
                  className="rounded-xl border border-line-input px-3.5 py-2.5 text-sm"
                />
              </label>
              <Button
                disabled={approve.isPending || !r.sequence.rows.length}
                onClick={() => (open.length ? setConfirm(true) : doApprove(false))}
              >
                {plan.needs_reapproval ? "Approve again" : "Approve plan"}
              </Button>
              <Button variant="pill" onClick={() => go(2)}>
                Send back to edit
              </Button>
            </>
          ) : (
            <p className="m-0 text-sm text-muted">Only the owner can approve the plan.</p>
          )}
          <span className="text-[13px] text-muted">
            When approved, purchase requests go to Purchasing, the schedule goes to Production, and
            promised dates are added to each order.
          </span>
          <div className="border-t border-divider pt-3.5">
            <h4 className="m-0 mb-2 text-sm font-semibold">History</h4>
            {(history.data ?? []).slice(0, 12).map((h, i) => (
              <div key={i} className="flex gap-3 py-2">
                <i className="mt-1.5 size-2 flex-none rounded-full bg-primary" />
                <div>
                  <b className="block text-[13px] font-semibold">{h.summary}</b>
                  <small className="text-xs text-muted">
                    {dateTime(h.at)}
                    {h.tabs.length ? ` · ${plural(h.tabs.length, "tab")} changed` : ""}
                  </small>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </div>

      <div className="flex justify-start">
        <Button variant="pill" onClick={() => go(4)}>
          ← Financial analysis
        </Button>
      </div>

      {confirm && open.length > 0 && (
        <Modal
          open
          tone="warning"
          onOpenChange={setConfirm}
          title={`Approve with ${plural(open.length, "open item")}?`}
          description={
            <>
              {open.map((n) => `${n.qty} ${n.unit} ${n.name}`).join(", ")}{" "}
              {open.length === 1 ? "isn't" : "aren't"} requested yet. If you approve, the purchase{" "}
              {open.length === 1 ? "request is" : "requests are"} recorded straight away. Needed by{" "}
              {shortDate(
                open.reduce((m, n) => (n.needed_by < m ? n.needed_by : m), open[0]!.needed_by),
              )}
              .
            </>
          }
          footer={
            <>
              <Button variant="pill" onClick={() => setConfirm(false)}>
                Go back
              </Button>
              <Button disabled={approve.isPending} onClick={() => doApprove(true)}>
                Approve and raise PO
              </Button>
            </>
          }
        />
      )}
    </section>
  );
}
