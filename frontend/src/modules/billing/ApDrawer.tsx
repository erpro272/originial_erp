import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Sheet } from "@/components/ui/Sheet";
import { LoadingState } from "@/components/ui/Skeleton";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { longDate } from "@/lib/format";
import { generatedLabel, isoDay } from "@/modules/planning/format";
import { usePurchases } from "@/modules/purchasing/api";
import { AP_STATUS, STEPS, inr, useApSupplier, useBillingAction, type ApInvoice } from "./api";
import { Communication, DrawerTabs, KV, Mini, field, lbl } from "./ArDrawer";

type Tab = "settlement" | "payments" | "approvals" | "comms";
type Act = "schedule" | "hold" | "reject" | "release" | { execute: string } | { confirm: string };

/** One supplier's invoices: where each payment is (7 steps), the three-way match, and the next action. */
export function ApDrawer({
  supplierId,
  month,
  onClose,
}: {
  supplierId: string;
  month: string | undefined;
  onClose: () => void;
}) {
  const s = useApSupplier(supplierId, month);
  const { can } = useAuth();
  const { toast } = useToast();
  const act = useBillingAction<ApInvoice>();
  const [pick, setPick] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("settlement");
  const [dialog, setDialog] = useState<Act | null>(null);
  const d = s.data;
  const inv = d?.invoices.find((i) => i.id === pick) ?? d?.invoices[0];
  const live = !!d?.period.live;
  const write = can("billing.write") && live;
  const owner = can("billing.approve") && live;
  const run = async (label: string, call: () => Promise<ApInvoice>) => {
    try {
      await act.mutateAsync(call);
      toast({ title: label, tone: "success" });
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't save.", tone: "error" });
    }
  };
  const path = (id: string) => ({ params: { path: { invoice_id: id } } });
  return (
    <Sheet
      open
      onOpenChange={(o) => !o && onClose()}
      eyebrow="Payment settlement"
      title={d?.name ?? "Supplier"}
      width={640}
      header={
        d && (
          <div className="mt-2 flex flex-col gap-3">
            {inv && (
              <span className="flex flex-wrap gap-1.5">
                {inv.days_overdue > 0 && inv.status !== "paid" && <Tag tone="hi">Overdue</Tag>}
                <Tag tone={AP_STATUS[inv.status].tone}>{AP_STATUS[inv.status].label}</Tag>
              </span>
            )}
            <div role="group" aria-label="Supplier invoices" className="flex flex-wrap gap-2">
              {d.invoices.map((i) => (
                <button
                  key={i.id}
                  type="button"
                  onClick={() => setPick(i.id)}
                  className={cn(
                    "cursor-pointer rounded-full border px-3 py-1.5 font-mono text-xs",
                    i.id === inv?.id
                      ? "border-inverse bg-inverse text-on-inverse"
                      : "border-line bg-card text-ink-2",
                  )}
                >
                  {i.number} · {inr(i.total_paise)}
                </button>
              ))}
            </div>
          </div>
        )
      }
    >
      {!d ? (
        <LoadingState label="Loading the supplier" />
      ) : !inv ? (
        <p className="m-0 text-sm text-muted">
          No supplier invoices as of {longDate(d.period.as_of)}.
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          <div className="flex divide-x divide-line rounded-card border border-line">
            <Mini label="Invoice amount" value={inr(inv.total_paise)} />
            <Mini label="Amount paid" value={inr(inv.paid_paise)} tone="ok" />
            <Mini
              label="Outstanding"
              value={inr(inv.outstanding_paise)}
              tone={inv.outstanding_paise ? "hi" : undefined}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            {inv.status === "pending_verif" && write && (
              <Button
                disabled={act.isPending}
                onClick={() =>
                  run(`${inv.number} verified`, async () =>
                    unwrap(
                      await api.POST(
                        "/api/billing/payables/invoices/{invoice_id}/verify",
                        path(inv.id),
                      ),
                    ),
                  )
                }
              >
                Verify (three-way match)
              </Button>
            )}
            {inv.status === "pending_owner" && owner && (
              <Button
                disabled={act.isPending}
                onClick={() =>
                  run(`${inv.number} approved`, async () =>
                    unwrap(
                      await api.POST(
                        "/api/billing/payables/invoices/{invoice_id}/approve",
                        path(inv.id),
                      ),
                    ),
                  )
                }
              >
                Approve payment
              </Button>
            )}
            {(inv.status === "approved" ||
              (inv.status === "scheduled" && inv.outstanding_paise > inv.scheduled_paise)) &&
              write && (
                <Button
                  variant={inv.status === "approved" ? "primary" : "pill"}
                  onClick={() => setDialog("schedule")}
                >
                  Schedule payment
                </Button>
              )}
            {["pending_verif", "pending_owner", "approved", "scheduled"].includes(inv.status) &&
              owner && (
                <Button variant="pill" className="text-hi" onClick={() => setDialog("hold")}>
                  Hold / Reject
                </Button>
              )}
            {inv.status === "on_hold" && owner && (
              <Button variant="pill" onClick={() => setDialog("release")}>
                Release hold
              </Button>
            )}
            {inv.deal_id && (
              <Link to={`/billing/ebill?deal=${inv.deal_id}`} className="ml-auto no-underline">
                <Tag tone="bl">{inv.deal_number} →</Tag>
              </Link>
            )}
          </div>
          <p className="m-0 -mt-2 text-[13px] text-muted">{nextText(inv, write, owner, live)}</p>
          <DrawerTabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "settlement", label: "Settlement" },
              { id: "payments", label: `Payment history (${inv.payments.length})` },
              { id: "approvals", label: "Approval history" },
              { id: "comms", label: "Communication" },
            ]}
          />
          {tab === "settlement" && <Settlement inv={inv} />}
          {tab === "payments" && <PaymentList inv={inv} write={write} onAct={setDialog} />}
          {tab === "approvals" && (
            <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
              {inv.events.map((e, i) => (
                <li
                  key={i}
                  className="flex flex-col border-b border-divider pb-2.5 text-sm last:border-0"
                >
                  <b className="font-semibold">{e.action}</b>
                  {e.note && <span className="text-[13px]">{e.note}</span>}
                  <span className="text-xs text-muted">
                    {generatedLabel(e.at)}
                    {e.by ? ` · ${e.by}` : ""}
                    {e.from_status !== e.to_status && e.to_status
                      ? ` · ${AP_STATUS[e.from_status as keyof typeof AP_STATUS]?.label ?? e.from_status} → ${AP_STATUS[e.to_status as keyof typeof AP_STATUS]?.label ?? e.to_status}`
                      : ""}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {tab === "comms" && <Communication items={d.interactions} />}
        </div>
      )}
      {dialog && inv && (
        <ApDialog
          act={dialog}
          inv={inv}
          owner={can("billing.approve")}
          onClose={() => setDialog(null)}
        />
      )}
    </Sheet>
  );
}

function nextText(inv: ApInvoice, write: boolean, owner: boolean, live: boolean): string {
  if (!live) return "Viewing a past month: actions are available in the current period.";
  const who = {
    pending_verif: "Accounts check it against the PO and the goods received.",
    pending_owner: "Verified by accounts. The owner decides: approve it, hold it, or reject it.",
    approved: "Approved by the owner. Accounts schedule the payment.",
    scheduled: "Scheduled. Accounts send it from the bank (UTR); it counts once the bank confirms.",
    paid: "Settled: every rupee sent and confirmed by the bank.",
    on_hold: `On hold: ${inv.hold_reason ?? ""}. Releasing it sends it back to the owner.`,
    rejected: `Rejected (disputed): ${inv.hold_reason ?? ""}. Not counted in payables.`,
  }[inv.status];
  return who + (!write && !owner ? " Read-only for your role." : "");
}

function Settlement({ inv }: { inv: ApInvoice }) {
  return (
    <div className="flex flex-col gap-5">
      <section aria-label="Where this payment is" className="flex flex-col gap-3">
        <h3 className="m-0 text-xs font-semibold tracking-[0.06em] text-muted uppercase">
          Where this payment is
        </h3>
        <ol className="m-0 grid list-none grid-cols-7 gap-1 p-0">
          {STEPS.map((label, i) => {
            const n = i + 1;
            const done = n < inv.stage || inv.stage === 7;
            const here = n === inv.stage && inv.stage !== 7;
            return (
              <li
                key={label}
                aria-current={here ? "step" : undefined}
                className="flex flex-col items-center gap-1.5 text-center"
              >
                <span
                  className={cn(
                    "grid size-6 place-items-center rounded-full border text-[11px]",
                    done
                      ? "border-primary bg-primary text-white"
                      : here
                        ? "border-primary text-primary"
                        : "border-line text-subtle",
                  )}
                >
                  {done ? "✓" : n}
                </span>
                <span
                  className={cn(
                    "text-[11px] leading-tight",
                    here ? "font-semibold text-ink" : "text-muted",
                  )}
                >
                  {label}
                </span>
              </li>
            );
          })}
        </ol>
      </section>
      <section aria-label="Three-way match" className="flex flex-col gap-2">
        <h3 className="m-0 text-xs font-semibold tracking-[0.06em] text-muted uppercase">
          3-way match (accounts verification)
        </h3>
        {inv.match.map((m) => (
          <span key={m.check} className={cn("flex items-start gap-2 text-sm", !m.ok && "text-hi")}>
            <span aria-hidden className={m.ok ? "text-ok" : "text-hi"}>
              {m.ok ? "✓" : "✕"}
            </span>
            {m.text}
          </span>
        ))}
      </section>
      <KV
        items={[
          ["Supplier invoice", inv.number],
          ["PO number", inv.po_number ?? "–"],
          ["Goods receipt (gate entry)", inv.grn ?? "–"],
          [
            "Billed",
            `${Number(inv.quantity).toLocaleString("en-IN")} ${inv.unit ?? ""} × ${inr(inv.rate_paise)}`,
          ],
          ["Taxable + GST", `${inr(inv.taxable_paise)} + ${inr(inv.gst_paise)}`],
          ["Invoice date", longDate(inv.invoice_date)],
          [
            "Original due date",
            `${longDate(inv.due_date)}${inv.days_overdue && inv.status !== "paid" ? ` · ${inv.days_overdue} days overdue` : ""}`,
          ],
          ["Scheduled (not paid)", inr(inv.scheduled_paise)],
        ]}
      />
    </div>
  );
}

function PaymentList({
  inv,
  write,
  onAct,
}: {
  inv: ApInvoice;
  write: boolean;
  onAct: (a: Act) => void;
}) {
  if (inv.payments.length === 0)
    return <p className="m-0 text-sm text-muted">No payment scheduled yet.</p>;
  const label = {
    scheduled: "Scheduled (a plan)",
    executed: "Sent · waiting for the bank",
    confirmed: "Bank confirmed",
    cancelled: "Cancelled",
  } as Record<string, string>;
  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0">
      {inv.payments.map((p) => (
        <li
          key={p.id}
          className="flex flex-wrap items-center justify-between gap-3 border-b border-divider pb-3 text-sm last:border-0"
        >
          <span className="flex flex-col">
            <b className="font-semibold">{inr(p.amount_paise)}</b>
            <span className="text-xs text-muted">
              {label[p.status] ?? p.status} · for {longDate(p.scheduled_for)}
              {p.utr ? ` · UTR ${p.utr}` : ""}
              {p.confirmed_on ? ` · confirmed ${longDate(p.confirmed_on)}` : ""}
              {p.override_reason ? ` · owner override: ${p.override_reason}` : ""}
            </span>
          </span>
          {write && p.status === "scheduled" && inv.status === "scheduled" && (
            <Button size="sm" variant="dark" onClick={() => onAct({ execute: p.id })}>
              Execute payment
            </Button>
          )}
          {write && p.status === "executed" && (
            <Button size="sm" variant="pill" onClick={() => onAct({ confirm: p.id })}>
              Bank confirmation
            </Button>
          )}
        </li>
      ))}
    </ol>
  );
}

function ApDialog({
  act,
  inv,
  owner,
  onClose,
}: {
  act: Act;
  inv: ApInvoice;
  owner: boolean;
  onClose: () => void;
}) {
  const run = useBillingAction<ApInvoice>();
  const { toast } = useToast();
  const today = isoDay(new Date());
  const pay =
    typeof act === "object"
      ? inv.payments.find((p) => p.id === ("execute" in act ? act.execute : act.confirm))
      : undefined;
  const room = inv.outstanding_paise - inv.scheduled_paise;
  const [amount, setAmount] = useState(String((pay?.amount_paise ?? room) / 100));
  const [date, setDate] = useState(today);
  const [text, setText] = useState("");
  const [utr, setUtr] = useState(pay?.utr ?? "");
  const [reject, setReject] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const paise = Math.round(Number(amount) * 100);
  const kind = typeof act === "object" ? ("execute" in act ? "execute" : "confirm") : act;
  const meta = {
    schedule: {
      title: `Schedule payment · ${inv.number}`,
      button: "Schedule",
      ok: paise > 0 && paise <= room && date >= today,
    },
    hold: {
      title: `Hold or reject · ${inv.number}`,
      button: reject ? "Reject invoice" : "Put on hold",
      ok: !!text.trim(),
    },
    reject: { title: `Reject · ${inv.number}`, button: "Reject invoice", ok: !!text.trim() },
    release: {
      title: `Release hold · ${inv.number}`,
      button: "Release (back to owner approval)",
      ok: !!text.trim(),
    },
    execute: {
      title: `Execute payment · ${inv.number}`,
      button: "Mark sent",
      ok: utr.trim().length >= 4 && date <= today,
    },
    confirm: {
      title: `Bank confirmation · ${inv.number}`,
      button: "Confirm from statement",
      ok: utr.trim().length >= 4 && paise > 0,
    },
  }[kind];
  const save = async () => {
    setErr(null);
    try {
      await run.mutateAsync(async () => {
        const ip = { params: { path: { invoice_id: inv.id } } };
        if (kind === "schedule")
          return unwrap(
            await api.POST("/api/billing/payables/invoices/{invoice_id}/schedule", {
              ...ip,
              body: { amount_paise: paise, scheduled_for: date },
            }),
          );
        if (kind === "hold" || kind === "reject" || kind === "release") {
          const action =
            kind === "release" ? "release" : reject || kind === "reject" ? "reject" : "hold";
          return unwrap(
            await api.POST("/api/billing/payables/invoices/{invoice_id}/{action}", {
              params: { path: { invoice_id: inv.id, action } },
              body: { reason: text.trim() },
            }),
          );
        }
        const pp = { params: { path: { payment_id: pay!.id } } };
        if (kind === "execute")
          return unwrap(
            await api.POST("/api/billing/payables/payments/{payment_id}/execute", {
              ...pp,
              body: { utr: utr.trim(), executed_on: date, override_reason: text.trim() || null },
            }),
          );
        return unwrap(
          await api.POST("/api/billing/payables/payments/{payment_id}/bank-confirm", {
            ...pp,
            body: { utr: utr.trim(), amount_paise: paise, confirmed_on: date },
          }),
        );
      });
      toast({ title: meta.button.replace(/^Mark sent$/, "Payment sent"), tone: "success" });
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Couldn't save.");
    }
  };
  return (
    <Modal
      open
      tone={kind === "hold" || kind === "reject" ? "danger" : "default"}
      onOpenChange={(o) => !o && onClose()}
      title={meta.title}
      description={`${inv.supplier} · outstanding ${inr(inv.outstanding_paise)}`}
      width={460}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button disabled={!meta.ok || run.isPending} onClick={save}>
            {meta.button}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {(kind === "schedule" || kind === "confirm") && (
          <label className={lbl}>
            Amount (₹)
            <input
              className={field}
              inputMode="decimal"
              value={amount}
              readOnly={kind === "confirm"}
              onChange={(e) => setAmount(e.target.value)}
            />
            {kind === "schedule" && (
              <span className="font-normal text-muted">
                {inr(room)} left to schedule. A schedule is a plan: it doesn't reduce what is owed.
              </span>
            )}
          </label>
        )}
        {(kind === "execute" || kind === "confirm") && (
          <label className={lbl}>
            UTR (bank reference)
            <input className={field} value={utr} onChange={(e) => setUtr(e.target.value)} />
          </label>
        )}
        {(kind === "schedule" || kind === "execute" || kind === "confirm") && (
          <label className={lbl}>
            {kind === "schedule"
              ? "Pay on"
              : kind === "execute"
                ? "Sent on"
                : "Date on the bank statement"}
            <input
              className={field}
              type="date"
              min={kind === "schedule" ? today : undefined}
              max={kind === "schedule" ? undefined : today}
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
        )}
        {kind === "execute" && owner && (
          <label className={lbl}>
            Override reason{" "}
            <span className="font-normal text-subtle">
              (only if you approved this payment yourself; logged)
            </span>
            <input className={field} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
        )}
        {kind === "hold" && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={reject} onChange={(e) => setReject(e.target.checked)} />
            Reject it (disputed: taken out of payables) instead of holding it
          </label>
        )}
        {(kind === "hold" || kind === "reject" || kind === "release") && (
          <label className={lbl}>
            Reason
            <textarea
              rows={3}
              className={field}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            {kind === "hold" && (
              <span className="font-normal text-muted">Any scheduled payment is cancelled.</span>
            )}
          </label>
        )}
        {err && (
          <p role="alert" className="m-0 text-sm text-hi">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}

/** A supplier invoice arrives: entered against its PO; the three-way match runs straight away. */
export function SupplierInvoiceDialog({
  onClose,
  poId: fixed,
}: {
  onClose: () => void;
  poId?: string;
}) {
  const pur = usePurchases();
  const act = useBillingAction<ApInvoice>();
  const { toast } = useToast();
  const today = isoDay(new Date());
  const pos = (pur.data?.purchase_orders ?? []).filter(
    (p) => !["awaiting_approval", "cancelled"].includes(p.status),
  );
  const [poId, setPoId] = useState(fixed ?? "");
  const po = pos.find((p) => p.id === poId);
  const ln = po?.lines[0];
  const [number, setNumber] = useState("");
  const [date, setDate] = useState(today);
  const [qty, setQty] = useState("");
  const [rate, setRate] = useState("");
  const [gst, setGst] = useState("18");
  const [err, setErr] = useState<string | null>(null);
  const choose = (id: string) => {
    setPoId(id);
    const l = pos.find((p) => p.id === id)?.lines[0];
    if (l) {
      setQty(String(Number(l.received_qty) || Number(l.quantity)));
      setRate(String(l.price_per_unit_paise / 100));
    }
  };
  const ok = !!po && !!number.trim() && Number(qty) > 0 && Number(rate) > 0 && date <= today;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Supplier invoice received"
      description="Entered against its purchase order. Accounts verify it once PO, goods received and invoice agree."
      width={520}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!ok || act.isPending}
            onClick={async () => {
              setErr(null);
              try {
                const r = await act.mutateAsync(async () =>
                  unwrap(
                    await api.POST("/api/billing/payables/invoices", {
                      body: {
                        po_id: poId,
                        number: number.trim(),
                        invoice_date: date,
                        quantity: qty,
                        rate_paise: Math.round(Number(rate) * 100),
                        gst_rate: gst,
                      },
                    }),
                  ),
                );
                toast({
                  title: `${r.number} recorded`,
                  description: r.match_ok
                    ? "Three-way match agrees"
                    : "Three-way match differs: see the payable",
                  tone: r.match_ok ? "success" : "error",
                });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't save.");
              }
            }}
          >
            Record invoice
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className={`${lbl} sm:col-span-2`}>
          Purchase order
          <select className={field} value={poId} onChange={(e) => choose(e.target.value)}>
            <option value="">Choose a PO…</option>
            {pos.map((p) => (
              <option key={p.id} value={p.id}>
                {p.number} · {p.supplier} · {p.lines[0]?.material}
              </option>
            ))}
          </select>
          {ln && (
            <span className="font-normal text-muted">
              Ordered {Number(ln.quantity)} {ln.unit} at {inr(ln.price_per_unit_paise)} · QC
              accepted {Number(ln.received_qty)} {ln.unit}
            </span>
          )}
        </label>
        <label className={lbl}>
          Invoice number
          <input className={field} value={number} onChange={(e) => setNumber(e.target.value)} />
        </label>
        <label className={lbl}>
          Invoice date
          <input
            className={field}
            type="date"
            max={today}
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Quantity billed {ln ? `(${ln.unit})` : ""}
          <input
            className={field}
            inputMode="decimal"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Rate (₹ per unit)
          <input
            className={field}
            inputMode="decimal"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
          />
        </label>
        <label className={lbl}>
          GST %
          <select className={field} value={gst} onChange={(e) => setGst(e.target.value)}>
            {["0", "5", "12", "18", "28"].map((g) => (
              <option key={g} value={g}>
                {g}%
              </option>
            ))}
          </select>
        </label>
        {err && (
          <p role="alert" className="m-0 text-sm text-hi sm:col-span-2">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}
