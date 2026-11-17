import { useState, type ReactNode } from "react";
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
import { longDate, shortDate } from "@/lib/format";
import { generatedLabel, isoDay } from "@/modules/planning/format";
import {
  AR_STATUS,
  inr,
  useArCustomer,
  useBillingAction,
  type ArInvoice,
  type Interaction,
} from "./api";

export const field = "w-full rounded-xl border border-line-input px-3.5 py-2.5 text-sm font-normal";
export const lbl = "flex flex-col gap-1.5 text-[13px] font-medium text-ink-2";

export function Mini({ label, value, tone }: { label: string; value: string; tone?: "hi" | "ok" }) {
  return (
    <div className="flex flex-1 flex-col gap-0.5 px-4 py-3">
      <span className="text-xs text-muted">{label}</span>
      <b
        className={cn(
          "text-[19px] font-semibold",
          tone === "hi" ? "text-hi" : tone === "ok" ? "text-ok" : "text-ink",
        )}
      >
        {value}
      </b>
    </div>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="flex flex-col gap-0.5">
          <dt className="text-xs text-muted">{k}</dt>
          <dd className="m-0 font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function DrawerTabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (t: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-5 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={t.id === value}
          onClick={() => onChange(t.id)}
          className={cn(
            "-mb-px cursor-pointer border-0 border-b-2 bg-transparent px-0 pb-2.5 text-sm",
            t.id === value
              ? "border-ink font-semibold text-ink"
              : "border-transparent text-muted hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Communication({ items }: { items: Interaction[] }) {
  if (items.length === 0)
    return <p className="m-0 text-sm text-muted">No calls, messages or visits logged yet.</p>;
  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0">
      {items.map((i) => (
        <li
          key={i.id}
          className="flex flex-col gap-0.5 border-b border-divider pb-3 text-sm last:border-0"
        >
          <span className="flex flex-wrap items-center gap-2">
            <Tag tone={i.direction === "incoming" ? "bl" : "ok"} size="sm">
              {i.direction === "incoming" ? "Incoming" : "Outgoing"} {i.channel}
            </Tag>
            {i.invoice_number && (
              <span className="font-mono text-xs text-muted">{i.invoice_number}</span>
            )}
            {i.deal_number && <span className="font-mono text-xs text-muted">{i.deal_number}</span>}
          </span>
          <span>{i.summary}</span>
          <span className="text-xs text-muted">
            {generatedLabel(i.at)}
            {i.by ? ` · ${i.by}` : ""}
            {i.contact ? ` · ${i.contact}` : ""}
            {i.next_follow_up ? ` · next follow-up ${shortDate(i.next_follow_up)}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

type Tab = "commitment" | "comms" | "payments";

/** One customer's open invoices as of the period: the three dates, communication and payments. */
export function ArDrawer({
  customerId,
  month,
  onClose,
}: {
  customerId: string;
  month: string | undefined;
  onClose: () => void;
}) {
  const c = useArCustomer(customerId, month);
  const { can } = useAuth();
  const [pick, setPick] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("commitment");
  const [dialog, setDialog] = useState<"follow" | "promise" | "receipt" | null>(null);
  const d = c.data;
  const inv = d?.invoices.find((i) => i.id === pick) ?? d?.invoices[0];
  const live = !!d?.period.live;
  const write = can("billing.write") && live;
  const worst = d?.invoices[0]?.status;
  return (
    <Sheet
      open
      onOpenChange={(o) => !o && onClose()}
      eyebrow="Receivable"
      title={d?.name ?? "Customer"}
      description={
        d ? [d.gstin, d.city, d.phone].filter(Boolean).join(" · ") || undefined : undefined
      }
      header={
        d && (
          <div className="mt-2 flex flex-col gap-3">
            <span className="flex flex-wrap gap-1.5">
              {worst && <Tag tone={AR_STATUS[worst].tone}>{AR_STATUS[worst].label}</Tag>}
              {d.invoices.some((i) => i.part_paid) && <Tag tone="lo">Part-paid</Tag>}
            </span>
            <div role="group" aria-label="Open invoices" className="flex flex-wrap gap-2">
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
                  {i.number ?? "—"} · {inr(i.outstanding_paise)}
                </button>
              ))}
            </div>
          </div>
        )
      }
    >
      {!d ? (
        <LoadingState label="Loading the customer" />
      ) : !inv ? (
        <p className="m-0 text-sm text-muted">
          Nothing outstanding as of {longDate(d.period.as_of)}.
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          <div className="flex divide-x divide-line rounded-card border border-line">
            <Mini label="Invoice amount" value={inr(inv.total_paise)} />
            <Mini label="Paid" value={inr(inv.received_paise)} tone="ok" />
            <Mini label="Outstanding" value={inr(inv.outstanding_paise)} tone="hi" />
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            {write ? (
              <>
                <Button variant="dark" onClick={() => setDialog("follow")}>
                  Log follow-up
                </Button>
                <Button variant="pill" onClick={() => setDialog("promise")}>
                  Update commitment
                </Button>
                <Button variant="pill" onClick={() => setDialog("receipt")}>
                  Record receipt
                </Button>
              </>
            ) : (
              <span className="text-[13px] text-muted">
                {live
                  ? "Read-only for your role."
                  : "Switch to the current period to log follow-ups and commitments."}
              </span>
            )}
            {inv.deal_id && (
              <Link to={`/billing/ebill?deal=${inv.deal_id}`} className="ml-auto no-underline">
                <Tag tone="bl">{inv.deal_number} →</Tag>
              </Link>
            )}
          </div>
          <DrawerTabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "commitment", label: "Commitment" },
              { id: "comms", label: `Communication (${d.interactions.length})` },
              { id: "payments", label: `Payment history (${inv.receipts.length})` },
            ]}
          />
          {tab === "commitment" && (
            <Commitment inv={inv} terms={d.payment_terms_days} email={d.email} phone={d.phone} />
          )}
          {tab === "comms" && <Communication items={d.interactions} />}
          {tab === "payments" && <Payments inv={inv} />}
        </div>
      )}
      {dialog && d && inv && (
        <ArDialog
          kind={dialog}
          customerId={d.customer_id}
          inv={inv}
          onClose={() => setDialog(null)}
        />
      )}
    </Sheet>
  );
}

function Commitment({
  inv,
  terms,
  email,
  phone,
}: {
  inv: ArInvoice;
  terms: number | null;
  email: string | null;
  phone: string | null;
}) {
  return (
    <div className="flex flex-col gap-5">
      <section aria-label="Three dates" className="grid gap-3 sm:grid-cols-3">
        {[
          [
            "Original due date",
            inv.due_date ? longDate(inv.due_date) : "–",
            inv.days_overdue ? `${inv.days_overdue} days overdue` : "contract: never changes",
          ],
          [
            "Promised payment date",
            inv.promised_on ? longDate(inv.promised_on) : "No promise yet",
            inv.promises.length
              ? `${inv.promises.length} promise${inv.promises.length > 1 ? "s" : ""} on record`
              : "what the customer says",
          ],
          [
            "Actual payment date",
            inv.receipts.length
              ? longDate(inv.receipts[inv.receipts.length - 1]!.received_on)
              : "Not paid yet",
            "from receipts only",
          ],
        ].map(([k, v, s]) => (
          <div key={k} className="flex flex-col gap-0.5 rounded-xl border border-line px-3.5 py-3">
            <span className="text-xs text-muted">{k}</span>
            <b className="text-sm font-semibold">{v}</b>
            <span
              className={cn(
                "text-xs",
                k === "Original due date" && inv.days_overdue ? "text-hi" : "text-subtle",
              )}
            >
              {s}
            </span>
          </div>
        ))}
      </section>
      <KV
        items={[
          ["Invoice", inv.number ?? "–"],
          ["Invoice date", inv.invoice_date ? longDate(inv.invoice_date) : "–"],
          ["Payment terms", terms ? `${terms} days` : "–"],
          ["Expected", inv.expected_on ? longDate(inv.expected_on) : "–"],
          ["Phone", phone ?? "–"],
          ["Email", email ?? "–"],
        ]}
      />
      {inv.promises.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="m-0 text-sm font-semibold">Promise history</h3>
          {inv.promises.map((p, i) => (
            <span
              key={i}
              className={cn("text-[13px]", i > 0 && "text-muted line-through decoration-faint")}
            >
              {inr(p.amount_paise)} by {longDate(p.promised_on)}
              {p.note ? ` · ${p.note}` : ""} · recorded {generatedLabel(p.at)}
              {p.by ? ` by ${p.by}` : ""}
            </span>
          ))}
        </section>
      )}
    </div>
  );
}

function Payments({ inv }: { inv: ArInvoice }) {
  if (inv.receipts.length === 0)
    return <p className="m-0 text-sm text-muted">No payment received on this invoice yet.</p>;
  const kind = {
    receipt: "Receipt",
    advance: "Advance adjusted",
    credit_note: "Credit note",
    opening: "Paid before Billing",
  } as Record<string, string>;
  return (
    <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
      {inv.receipts.map((r) => (
        <li
          key={r.id}
          className="flex items-center justify-between gap-3 border-b border-divider pb-2.5 text-sm last:border-0"
        >
          <span className="flex flex-col">
            <b className="font-semibold">{kind[r.kind] ?? r.kind}</b>
            <span className="text-xs text-muted">
              {longDate(r.received_on)}
              {r.method ? ` · ${r.method.toUpperCase()}` : ""}
              {r.reference ? ` · ${r.reference}` : ""}
              {r.by ? ` · ${r.by}` : ""}
            </span>
          </span>
          <b className="font-semibold text-ok">{inr(r.amount_paise)}</b>
        </li>
      ))}
    </ol>
  );
}

function ArDialog({
  kind,
  customerId,
  inv,
  onClose,
}: {
  kind: "follow" | "promise" | "receipt";
  customerId: string;
  inv: ArInvoice;
  onClose: () => void;
}) {
  const act = useBillingAction<unknown>();
  const { toast } = useToast();
  const today = isoDay(new Date());
  const [channel, setChannel] = useState<"call" | "whatsapp" | "email" | "visit" | "meeting">(
    "call",
  );
  const [note, setNote] = useState("");
  const [next, setNext] = useState("");
  const [amount, setAmount] = useState(String(inv.outstanding_paise / 100));
  const [date, setDate] = useState(today);
  const [method, setMethod] = useState<"neft" | "rtgs" | "imps" | "upi" | "cheque" | "cash">(
    "neft",
  );
  const [ref, setRef] = useState("");
  const [rkind, setRkind] = useState<"receipt" | "advance" | "credit_note">("receipt");
  const [err, setErr] = useState<string | null>(null);
  const paise = Math.round(Number(amount) * 100);
  const meta = {
    follow: { title: `Log follow-up · ${inv.number}`, button: "Save follow-up", ok: !!note.trim() },
    promise: {
      title: `Update commitment · ${inv.number}`,
      button: "Save promise",
      ok: paise > 0 && paise <= inv.outstanding_paise && date >= today,
    },
    receipt: {
      title: `Record receipt · ${inv.number}`,
      button: "Save receipt",
      ok: paise > 0 && paise <= inv.outstanding_paise && date <= today,
    },
  }[kind];
  const save = async () => {
    setErr(null);
    try {
      await act.mutateAsync(async () => {
        if (kind === "follow")
          return unwrap(
            await api.POST("/api/billing/receivables/customers/{customer_id}/follow-ups", {
              params: { path: { customer_id: customerId } },
              body: {
                invoice_id: inv.id,
                channel,
                direction: "outgoing",
                note: note.trim(),
                next_follow_up: next || null,
              },
            }),
          );
        if (kind === "promise")
          return unwrap(
            await api.POST("/api/billing/receivables/invoices/{invoice_id}/promises", {
              params: { path: { invoice_id: inv.id } },
              body: { amount_paise: paise, promised_on: date, note: note.trim() || null },
            }),
          );
        return unwrap(
          await api.POST("/api/billing/receivables/invoices/{invoice_id}/receipts", {
            params: { path: { invoice_id: inv.id } },
            body: {
              kind: rkind,
              amount_paise: paise,
              received_on: date,
              method: rkind === "receipt" ? method : null,
              reference: ref.trim() || null,
              note: note.trim() || null,
            },
          }),
        );
      });
      toast({
        title:
          kind === "follow"
            ? "Follow-up logged"
            : kind === "promise"
              ? "Commitment updated"
              : `${inr(paise)} recorded`,
        tone: "success",
      });
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Couldn't save.");
    }
  };
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={meta.title}
      description={`${inr(inv.outstanding_paise)} outstanding · due ${inv.due_date ? longDate(inv.due_date) : "–"}`}
      width={460}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button disabled={!meta.ok || act.isPending} onClick={save}>
            {meta.button}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {kind === "follow" && (
          <>
            <label className={lbl}>
              Channel
              <select
                className={field}
                value={channel}
                onChange={(e) => setChannel(e.target.value as typeof channel)}
              >
                {["call", "whatsapp", "email", "visit", "meeting"].map((x) => (
                  <option key={x} value={x}>
                    {x === "whatsapp" ? "WhatsApp" : x[0]!.toUpperCase() + x.slice(1)}
                  </option>
                ))}
              </select>
            </label>
            <label className={lbl}>
              What was said
              <textarea
                rows={3}
                className={field}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
            <label className={lbl}>
              Next follow-up <span className="font-normal text-subtle">(optional)</span>
              <input
                className={field}
                type="date"
                min={today}
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            </label>
          </>
        )}
        {kind === "receipt" && (
          <label className={lbl}>
            Type
            <select
              className={field}
              value={rkind}
              onChange={(e) => setRkind(e.target.value as typeof rkind)}
            >
              <option value="receipt">Payment received</option>
              <option value="advance">Advance adjusted</option>
              <option value="credit_note">Credit note</option>
            </select>
          </label>
        )}
        {kind !== "follow" && (
          <>
            <label className={lbl}>
              Amount (₹)
              <input
                className={field}
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </label>
            <label className={lbl}>
              {kind === "promise" ? "Customer will pay by" : "Date"}
              <input
                className={field}
                type="date"
                min={kind === "promise" ? today : undefined}
                max={kind === "receipt" ? today : undefined}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
          </>
        )}
        {kind === "receipt" && rkind === "receipt" && (
          <>
            <label className={lbl}>
              Method
              <select
                className={field}
                value={method}
                onChange={(e) => setMethod(e.target.value as typeof method)}
              >
                {["neft", "rtgs", "imps", "upi", "cheque", "cash"].map((x) => (
                  <option key={x} value={x}>
                    {x.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <label className={lbl}>
              UTR / cheque no.
              <input className={field} value={ref} onChange={(e) => setRef(e.target.value)} />
            </label>
          </>
        )}
        {kind !== "follow" && (
          <label className={lbl}>
            Note <span className="font-normal text-subtle">(optional)</span>
            <input className={field} value={note} onChange={(e) => setNote(e.target.value)} />
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
