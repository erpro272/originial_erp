import { useState, type ReactNode } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { rupees, rupeesCompact, shortDate } from "@/lib/format";
import { useApprove, useHistory, useRaisePo, useSendBack, type Plan } from "./api";
import { isWorking, planStatus } from "./status";
import { generatedLabel, plural, range } from "./format";
import { RuleButton } from "./RuleButton";

function money(paise: number): string {
  const abs = Math.abs(paise) / 100;
  if (abs >= 1e5) return `₹${(abs / 1e5).toFixed(2)} L`;
  return `₹${rupees(Math.abs(paise))}`;
}

/** Step 5: check the final order combination and schedule, then approve it. */
export function ApprovalStep({ plan, go }: { plan: Plan; go: (step: string) => void }) {
  const { can } = useAuth();
  const owner = can("planning.approve");
  const approved = plan.status === "approved";
  // approve a working plan; re-approve an approved one from its recalculated (live) version
  const decide = isWorking(plan) || (approved && plan.needs_reapproval && plan.view === "live");
  const canApprove = owner && decide;
  const r = plan.result;
  const seq = r.sequence;
  const fin = r.finance.with;
  const orders = r.selection.orders;
  const checks = r.approval.checks;
  // materials Purchasing still has to be asked for (stock and deliveries already on order excluded)
  const openPos = r.purchase_needs.filter((n) => n.action && !n.requested);
  const openChecks = checks.filter((c) => !c.ok);
  const fixes = r.finance.fixes.filter((f) => f.selected);
  const pins = seq.rows.filter((x) => x.pinned);
  const [note, setNote] = useState(plan.approval_note ?? "");
  const [confirm, setConfirm] = useState(false);
  const approve = useApprove(plan.id);
  const sendBack = useSendBack(plan.id);
  const raisePo = useRaisePo(plan.id);
  const history = useHistory(plan.id, plan.version);
  const { toast } = useToast();
  const busy = approve.isPending || sendBack.isPending || raisePo.isPending;
  const status = planStatus(plan);

  const fail = (e: unknown, fallback: string) =>
    toast({ title: e instanceof ApiError ? e.message : fallback, tone: "error" });

  const doApprove = async () => {
    try {
      await approve.mutateAsync({ note: note.trim() || null, raise_open_pos: openPos.length > 0 });
      setConfirm(false);
      toast({
        title: "Plan approved",
        description: `${openPos.length ? `${plural(openPos.length, "PO")} sent to Purchasing · ` : ""}promised dates added to ${plural(seq.rows.length, "order")}`,
        tone: "success",
      });
    } catch (e) {
      fail(e, "Couldn't approve the plan.");
    }
  };

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Final plan approval</h2>
          <p className="m-0 text-[15px] text-muted">
            Check the final order combination and schedule, then approve it to send it to Purchasing
            and Production.
          </p>
        </div>
        <Tag tone={status.tone}>{status.text}</Tag>
      </div>

      {plan.changes_requested && !approved && (
        <div
          role="status"
          className="rounded-card border border-hi-line bg-hi-wash px-5 py-3.5 text-sm"
        >
          <b>Sent back to edit</b> {generatedLabel(plan.changes_requested.at)}
          {plan.changes_requested.note ? ` · “${plan.changes_requested.note}”` : ""}
        </div>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(300px,1fr)]">
        <div className="flex flex-col gap-5">
          {/* summary */}
          <section
            aria-label="Plan summary"
            className="overflow-hidden rounded-card border border-line"
          >
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <h3 className="m-0 text-[17px] font-semibold">
                {plan.number}{" "}
                <small className="ml-1 text-[13px] font-normal text-muted">
                  {range(seq.overview.start, seq.overview.end).replace("–", " – ")} ·{" "}
                  {fixes.length
                    ? `${fixes.length} ${fixes.length === 1 ? "fix" : "fixes"} applied`
                    : "no fixes"}
                </small>
              </h3>
              <button
                type="button"
                onClick={() => go("3")}
                className="cursor-pointer border-0 bg-transparent p-0 text-[13px] text-link"
              >
                View schedule →
              </button>
            </div>
            <div className="grid grid-cols-2 border-t border-divider bg-surface sm:grid-cols-5">
              <Fig label="Orders" value={String(seq.overview.orders)} />
              <Fig label="Production days" value={String(seq.overview.days)} />
              <Fig label="Sales value" value={rupeesCompact(fin.value)} />
              <Fig label="Contribution" value={money(fin.contribution)} tone="ok" />
              <Fig label="Margin" value={`${fin.margin.toFixed(1)}%`} />
            </div>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-surface text-left text-xs font-semibold tracking-[0.04em] text-muted uppercase">
                  {["Order", "Customer", "Finishes", "Deadline", "Delivery"].map((h) => (
                    <th key={h} className="border-t border-divider px-5 py-3 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {seq.rows.map((row) => {
                  const o = orders[row.id]!;
                  return (
                    <tr key={row.id}>
                      <td className="border-t border-divider px-5 py-3 font-mono font-semibold">
                        {o.number}
                      </td>
                      <td className="border-t border-divider px-5 py-3">{o.customer}</td>
                      <td
                        className={cn(
                          "border-t border-divider px-5 py-3",
                          row.late_days && "font-semibold text-hi",
                        )}
                      >
                        {shortDate(row.finish)}
                      </td>
                      <td className="border-t border-divider px-5 py-3">
                        {shortDate(row.deadline)}
                      </td>
                      <td className="border-t border-divider px-5 py-3">
                        {row.late_days ? (
                          <Tag tone="hi" size="sm">
                            Late · {plural(row.late_days, "day")}
                          </Tag>
                        ) : (
                          <Tag tone="ok" size="sm">
                            On time
                          </Tag>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {(fixes.length > 0 || pins.length > 0 || plan.rule === "custom") && (
              <div className="flex flex-wrap items-center gap-2 border-t border-divider px-5 py-3.5 text-[13px] text-muted">
                <span>Fixes applied:</span>
                {fixes.map((f) => {
                  // an express fix is a plan assumption until its PO is actually raised
                  const need = r.purchase_needs.find((n) => f.id === `express:${n.material}`);
                  return (
                    <Chip key={f.id}>
                      {f.label} · {money(f.cost)}
                      {need?.action &&
                        (need.requested ? " · PO requested" : " · PO not raised yet")}
                      {(f.status === "no_effect" || f.status === "partly") &&
                        " · not resolving the delay"}
                      {f.status === "not_needed" && " · not needed"}
                    </Chip>
                  );
                })}
                {pins.map((p) => (
                  <Chip key={p.id}>
                    {orders[p.id]?.number} finishes {shortDate(p.pinned!)}
                  </Chip>
                ))}
                {plan.rule === "custom" && <Chip>Custom order of work</Chip>}
              </div>
            )}
          </section>

          {/* checklist */}
          <section
            aria-label="Readiness checklist"
            className="rounded-card border border-line p-[22px]"
          >
            <div className="mb-2 flex items-center justify-between">
              <h3 className="m-0 text-[17px] font-semibold">Readiness checklist</h3>
              <Tag tone={r.approval.ready === r.approval.total ? "ok" : "md"}>
                {r.approval.ready} of {r.approval.total} ready
              </Tag>
            </div>
            {checks.map((c) => (
              <div
                key={c.title}
                className="flex items-center gap-3.5 border-t border-divider py-3.5 first-of-type:border-t-0"
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid size-7 flex-none place-items-center rounded-full text-sm font-bold",
                    c.ok ? "bg-ok-bg text-ok" : "bg-md-bg text-md",
                  )}
                >
                  {c.ok ? "✓" : "!"}
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <b className="inline-flex items-center gap-1 text-sm">
                    {c.title}
                    {c.setting === "min_margin_pct" && <RuleButton rule="min_margin" />}
                  </b>
                  <CheckText check={c} />
                  {c.action === "raise_po" && !c.ok && (
                    <small className="text-xs text-subtle">
                      The PO goes to Purchasing when you approve, or raise it now.
                    </small>
                  )}
                </div>
                {c.action === "raise_po" && !c.ok && can("planning.write") && isWorking(plan) && (
                  <Button
                    variant="pill"
                    size="pill"
                    disabled={busy}
                    onClick={async () => {
                      try {
                        for (const n of openPos) await raisePo.mutateAsync(n.material);
                        toast({
                          title: `${plural(openPos.length, "PO")} sent to Purchasing`,
                          tone: "success",
                        });
                      } catch (e) {
                        fail(e, "Couldn't raise the PO.");
                      }
                    }}
                  >
                    Raise PO now
                  </Button>
                )}
              </div>
            ))}
          </section>
        </div>

        {/* owner approval + history */}
        <aside
          aria-label="Owner approval"
          className="flex flex-col gap-4 rounded-card border border-line p-[22px]"
        >
          <h3 className="m-0 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
            Owner approval
          </h3>
          {!decide ? (
            <p className="m-0 text-sm text-ink-2">
              {plan.status === "cancelled"
                ? `Cancelled${plan.cancel_reason ? `: “${plan.cancel_reason}”` : ""}. Nothing was sent to Purchasing or Production.`
                : `Approved ${plan.snapshot ? generatedLabel(plan.snapshot.approved_at) : plan.approved_at ? generatedLabel(plan.approved_at) : ""}${plan.snapshot?.note ? ` · “${plan.snapshot.note}”` : ""}. POs went to Purchasing and promised dates were added to each order. This is the approved version, read-only.`}
              {approved && plan.needs_reapproval && (
                <span className="mt-2 block text-hi">
                  Data has changed since: open the recalculated version (banner above) to
                  re-approve.
                </span>
              )}
            </p>
          ) : (
            <>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                <span>
                  Note <span className="font-normal text-subtle">(optional)</span>
                </span>
                <textarea
                  rows={3}
                  value={note}
                  disabled={!canApprove}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. Confirm night-shift crew with the supervisor"
                  className="resize-y rounded-xl border border-line-input px-3.5 py-2.5 text-sm font-normal"
                />
              </label>
              <Button
                className="w-full"
                disabled={!canApprove || busy}
                title={owner ? undefined : "Only the owner can approve the plan"}
                onClick={() => (openChecks.length ? setConfirm(true) : void doApprove())}
              >
                {plan.needs_reapproval ? "Approve again" : "Approve plan"}
              </Button>
              {!approved && (
                <Button
                  variant="pill"
                  className="w-full"
                  disabled={!owner || busy}
                  onClick={async () => {
                    try {
                      await sendBack.mutateAsync({ note: note.trim() || null });
                      toast({ title: "Sent back to edit", tone: "success" });
                      go("2");
                    } catch (e) {
                      fail(e, "Couldn't send it back.");
                    }
                  }}
                >
                  Send back to edit
                </Button>
              )}
              <span className="text-xs text-subtle">
                {owner
                  ? "When approved, POs go to Purchasing, the schedule goes to Production, and promised dates are added to each order."
                  : "Only the owner can approve or send the plan back."}
              </span>
            </>
          )}
          {(plan.snapshots ?? []).length > 0 && (
            <div className="flex flex-col gap-2 border-t border-divider pt-4">
              <h4 className="m-0 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
                Approved versions
              </h4>
              {(plan.snapshots ?? []).map((v) => (
                <span key={v.version} className="text-sm">
                  <b>v{v.version}</b>{" "}
                  <span className="text-muted">
                    {generatedLabel(v.approved_at)}
                    {v.note ? ` · “${v.note}”` : ""}
                    {plan.snapshot?.version === v.version ? " · shown" : ""}
                  </span>
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-col gap-3 border-t border-divider pt-4">
            <h4 className="m-0 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
              History
            </h4>
            {(history.data ?? []).slice(0, 12).map((h, i) => (
              <div key={`${h.at}${i}`} className="flex gap-3">
                <i
                  aria-hidden
                  className={cn(
                    "mt-1.5 size-2 flex-none rounded-full",
                    i < 3 ? "bg-primary" : "bg-faint",
                  )}
                />
                <div className="flex flex-col">
                  <b className="text-sm">{historyTitle(h.kind, h.summary)}</b>
                  <small className="text-xs text-muted">
                    {historyDetail(h.summary)}
                    {historyDetail(h.summary) ? " · " : ""}
                    {generatedLabel(h.at)}
                  </small>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </div>

      <div className="flex justify-between">
        <Button variant="pill" onClick={() => go("4")}>
          ← Financial analysis
        </Button>
      </div>

      {confirm && (
        <Modal
          open
          tone="danger"
          onOpenChange={(o) => !o && setConfirm(false)}
          title={`Approve with ${plural(openChecks.length, "open item")}?`}
          description={
            openPos.length
              ? "Approving sends the un-raised POs to Purchasing straight away. The rest stays open and is saved in the history."
              : "These stay open after approval and are saved in the history."
          }
          footer={
            <>
              <Button variant="pill" onClick={() => setConfirm(false)}>
                Go back
              </Button>
              <Button disabled={busy} onClick={() => void doApprove()}>
                {openPos.length ? "Approve and raise PO" : "Approve anyway"}
              </Button>
            </>
          }
        >
          <div className="flex flex-col">
            {openChecks.map((c) => (
              <div key={c.title} className="flex gap-3 border-t border-divider py-3 text-sm">
                <span className="mt-1.5 size-2 flex-none rounded-full bg-md-accent" />
                <div>
                  <b className="block">{c.title}</b>
                  <CheckText check={c} />
                </div>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </section>
  );
}

const TITLES: Record<string, string> = {
  created: "Plan started",
  generated: "Plan generated",
  saved: "Schedule saved",
  sent_back: "Sent back to edit",
  completed: "Plan completed",
  cancelled: "Plan cancelled",
  approved: "Plan approved",
  po: "PO requested",
  refresh: "Plan updated",
};

/** "Sequence changed · ORD-1044 moved" -> title "Sequence changed", detail "ORD-1044 moved". */
function historyTitle(kind: string, summary: string): string {
  return TITLES[kind] && kind !== "change" ? TITLES[kind]! : summary.split(" · ")[0]!;
}
function historyDetail(summary: string): string {
  return summary.split(" · ").slice(1).join(" · ");
}

function Fig({ label, value, tone }: { label: string; value: string; tone?: "ok" }) {
  return (
    <div className="flex flex-col gap-1 border-line px-5 py-4 not-first:border-l">
      <span className="text-[13px] text-muted">{label}</span>
      <b className={cn("text-[22px] leading-tight font-bold", tone === "ok" && "text-ok")}>
        {value}
      </b>
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md border border-line-input bg-surface-2 px-2 py-1 text-xs text-ink-2">
      {children}
    </span>
  );
}

/** A check's detail: one line per material when it has items (same lines in the popup). */
function CheckText({ check }: { check: Plan["result"]["approval"]["checks"][number] }) {
  if (!check.items?.length)
    return check.text ? <small className="text-[13px] text-muted">{check.text}</small> : null;
  return (
    <ul className="m-0 flex list-none flex-col gap-1 p-0">
      {check.items.map((i) => (
        <li key={i.material} className={cn("text-[13px]", i.open ? "text-ink-2" : "text-muted")}>
          {i.text}
        </li>
      ))}
    </ul>
  );
}
