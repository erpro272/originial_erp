import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { FilterChips } from "@/components/ui/FilterChips";
import { Tooltip } from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { Sheet } from "@/components/ui/Sheet";
import { LoadingState } from "@/components/ui/Skeleton";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { longDate } from "@/lib/format";
import { generatedLabel } from "@/modules/planning/format";
import {
  AP_STATUS,
  DEAL_TONE,
  STEPS,
  inr,
  useBillingAction,
  useDeal,
  type DealDetail,
} from "./api";
import { SupplierInvoiceDialog } from "./ApDrawer";
import { Communication, DrawerTabs, KV, Mini, field, lbl } from "./ArDrawer";

type Tab = "overview" | "documents" | "interactions" | "activity";
type Dir = "all" | "incoming" | "outgoing" | "internal";
const DIR_TONE = { incoming: "bl", outgoing: "ok", internal: "lo" } as const;

const qty = (x: string | number | null | undefined, unit: string | null | undefined) =>
  x == null
    ? "–"
    : `${Number(x).toLocaleString("en-IN", { maximumFractionDigits: 3 })} ${unit ?? ""}`.trim();

/** One deal: overview (money and readiness), documents, interactions and the full activity. */
export function DealDrawer({ dealId, onClose }: { dealId: string; onClose: () => void }) {
  const deal = useDeal(dealId);
  const { can } = useAuth();
  const { toast } = useToast();
  const act = useBillingAction<DealDetail>();
  const [tab, setTab] = useState<Tab>("overview");
  const [dir, setDir] = useState<Dir>("all");
  const [dialog, setDialog] = useState<"edit" | "send" | "interaction" | "supplier" | null>(null);
  const d = deal.data;
  const write = can("billing.write");
  const run = async (label: string, call: () => Promise<DealDetail>) => {
    try {
      await act.mutateAsync(call);
      toast({ title: label, tone: "success" });
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't save.", tone: "error" });
    }
  };
  const p = { params: { path: { deal_id: dealId } } };
  const inv = d?.invoice;
  const sale = d?.row.kind === "sale";
  return (
    <Sheet
      open
      onOpenChange={(o) => !o && onClose()}
      width={660}
      eyebrow={d ? `${sale ? "Sale deal" : "Purchase deal"} · ${d.row.number}` : "Deal"}
      title={d?.row.name ?? "Deal"}
      header={
        d && (
          <div className="mt-1 flex flex-col gap-2">
            <span className="text-sm text-muted">
              <Link
                to={
                  sale
                    ? `/billing?mode=ar&customer=${d.customer_id}`
                    : `/billing?mode=ap&supplier=${d.supplier_id}`
                }
              >
                {d.row.company}
              </Link>{" "}
              · {sale ? "Customer · Sales order" : "Supplier · Purchase order"}
            </span>
            <span className="flex flex-wrap gap-1.5">
              <Tag tone={DEAL_TONE[d.row.status] ?? "lo"}>{d.row.status}</Tag>
              {d.row.provisional && <Tag tone="md">Provisional</Tag>}
              {d.row.archived && <Tag tone="lo">Archived</Tag>}
            </span>
          </div>
        )
      }
      footer={
        d && (
          <>
            {sale && !inv && write && (
              <Tooltip content={d.invoice_block ?? "A draft from the dispatched order"}>
                <span>
                  <Button
                    disabled={!!d.invoice_block || act.isPending}
                    onClick={() =>
                      run("Invoice draft generated", async () =>
                        unwrap(await api.POST("/api/billing/deals/{deal_id}/invoice", p)),
                      )
                    }
                  >
                    Generate invoice
                  </Button>
                </span>
              </Tooltip>
            )}
            {sale && inv?.status === "draft" && write && (
              <Button
                disabled={act.isPending}
                onClick={() =>
                  run("Invoice verified", async () =>
                    unwrap(await api.POST("/api/billing/deals/{deal_id}/invoice/verify", p)),
                  )
                }
              >
                Verify invoice
              </Button>
            )}
            {sale && inv?.status === "verified" && can("billing.issue") && (
              <Button
                disabled={act.isPending}
                onClick={() =>
                  run("Invoice issued", async () =>
                    unwrap(await api.POST("/api/billing/deals/{deal_id}/invoice/issue", p)),
                  )
                }
              >
                Issue invoice
              </Button>
            )}
            {sale && (inv?.status === "issued" || inv?.status === "sent") && write && (
              <Button variant="pill" onClick={() => setDialog("send")}>
                Share
              </Button>
            )}
            {sale && (
              <Tooltip content="E-invoice (IRN) comes in the next round.">
                <span>
                  <Button variant="pill" disabled>
                    Generate e-invoice
                  </Button>
                </span>
              </Tooltip>
            )}
            {!sale && write && !d.payable && d.po_id && (
              <Button onClick={() => setDialog("supplier")}>Add supplier invoice</Button>
            )}
            {!sale && d.payable && (
              <Link to={`/billing?mode=ap&supplier=${d.supplier_id}`} className="no-underline">
                <Button variant="pill">Open payable</Button>
              </Link>
            )}
            <span className="flex-1" />
            {write && (
              <>
                <Button variant="pill" onClick={() => setDialog("interaction")}>
                  Add interaction
                </Button>
                {!d.row.archived && (
                  <Button
                    variant="pill"
                    onClick={() =>
                      run("Deal archived", async () =>
                        unwrap(await api.POST("/api/billing/deals/{deal_id}/archive", p)),
                      )
                    }
                  >
                    Archive
                  </Button>
                )}
              </>
            )}
          </>
        )
      }
    >
      {!d ? (
        <LoadingState label="Loading the deal" />
      ) : (
        <div className="flex flex-col gap-5">
          <DrawerTabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "overview", label: "Overview" },
              { id: "documents", label: `Documents (${d.documents.length})` },
              { id: "interactions", label: `Interactions (${d.interactions.length})` },
              { id: "activity", label: "Activity" },
            ]}
          />
          {tab === "overview" && (
            <Overview
              d={d}
              onEdit={() => setDialog("edit")}
              onActivity={() => setTab("activity")}
              canEdit={write}
            />
          )}
          {tab === "documents" && (
            <div className="flex flex-col gap-3">
              <FilterChips<Dir>
                label="Document direction"
                value={dir}
                onChange={setDir}
                options={(["all", "incoming", "outgoing", "internal"] as const).map((k) => ({
                  value: k,
                  label: k === "all" ? "All" : k[0]!.toUpperCase() + k.slice(1),
                  count:
                    k === "all"
                      ? d.documents.length
                      : d.documents.filter((x) => x.direction === k).length,
                }))}
              />
              <ol className="m-0 flex list-none flex-col p-0">
                {d.documents
                  .filter((x) => dir === "all" || x.direction === dir)
                  .map((x) => (
                    <li
                      key={x.key}
                      className="flex flex-wrap items-center justify-between gap-3 border-b border-divider py-3 text-sm last:border-0"
                    >
                      <span className="flex flex-col">
                        <b className="font-semibold">
                          {x.name}
                          {x.number ? (
                            <span className="ml-2 font-mono text-xs font-normal text-muted">
                              {x.number}
                            </span>
                          ) : null}
                        </b>
                        <span className="text-xs text-muted">
                          {x.date ? longDate(x.date) : "–"} · {x.source}
                          {x.amount_paise != null ? ` · ${inr(x.amount_paise)}` : ""}
                        </span>
                      </span>
                      <span className="flex gap-1.5">
                        <Tag tone={DIR_TONE[x.direction]} size="sm">
                          {x.direction[0]!.toUpperCase() + x.direction.slice(1)}
                        </Tag>
                        <Tag tone="lo" size="sm">
                          {x.status}
                        </Tag>
                      </span>
                    </li>
                  ))}
              </ol>
            </div>
          )}
          {tab === "interactions" && <Communication items={d.interactions} />}
          {tab === "activity" && <Activity d={d} />}
        </div>
      )}
      {dialog === "edit" && d && <DraftDialog d={d} onClose={() => setDialog(null)} />}
      {dialog === "send" && d && <SendDialog d={d} onClose={() => setDialog(null)} />}
      {dialog === "interaction" && d && <InteractionDialog d={d} onClose={() => setDialog(null)} />}
      {dialog === "supplier" && (
        <SupplierInvoiceDialog poId={d?.po_id ?? undefined} onClose={() => setDialog(null)} />
      )}
    </Sheet>
  );
}

function Overview({
  d,
  onEdit,
  onActivity,
  canEdit,
}: {
  d: DealDetail;
  onEdit: () => void;
  onActivity: () => void;
  canEdit: boolean;
}) {
  const sale = d.row.kind === "sale";
  const inv = d.invoice;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex divide-x divide-line rounded-card border border-line">
        <Mini
          label={sale ? "Deal value" : "PO value"}
          value={d.row.value_paise == null ? "—" : inr(d.row.value_paise)}
        />
        <Mini label={sale ? "Order qty" : "Ordered qty"} value={qty(d.quantity, d.unit)} />
        <Mini
          label={sale ? "Dispatched qty" : "Received qty"}
          value={qty(sale ? d.dispatched_qty : d.received_qty, d.unit)}
        />
        <Mini label="Documents" value={String(d.documents.length)} />
      </div>
      {sale && d.invoice_block && (
        <p
          role="status"
          className="m-0 rounded-xl border border-md-line bg-md-bg px-4 py-3 text-sm"
        >
          {d.invoice_block}
        </p>
      )}
      {sale && !inv && !d.invoice_block && (
        <p
          role="status"
          className="m-0 rounded-xl border border-ok-line bg-ok-bg px-4 py-3 text-sm"
        >
          Dispatched in full: ready to invoice. Generate the invoice from the footer.
        </p>
      )}
      {inv && (
        <section
          aria-label="Invoice"
          className="flex flex-col gap-3 rounded-card border border-line p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <b className="font-semibold">
              Tax invoice{" "}
              {inv.number ? (
                <span className="font-mono">{inv.number}</span>
              ) : (
                <span className="text-muted">(draft, no number yet)</span>
              )}
            </b>
            <Tag
              tone={inv.status === "draft" ? "md" : inv.status === "verified" ? "bl" : "ok"}
              size="sm"
            >
              {inv.status === "draft"
                ? "Draft"
                : inv.status === "verified"
                  ? "Verified"
                  : inv.status === "sent"
                    ? "Issued · sent"
                    : "Issued"}
            </Tag>
          </div>
          <KV
            items={[
              [
                "Quantity × rate",
                `${qty(inv.quantity, d.unit)} × ${inv.rate_paise != null ? inr(inv.rate_paise) : "–"}`,
              ],
              ["Taxable", inr(inv.taxable_paise + inv.other_charges_paise)],
              [
                "GST",
                inv.igst_paise
                  ? `IGST ${inr(inv.igst_paise)}`
                  : `CGST ${inr(inv.cgst_paise)} + SGST ${inr(inv.sgst_paise)}`,
              ],
              ["Total", inr(inv.total_paise)],
              ["Payment terms", inv.payment_terms_days ? `${inv.payment_terms_days} days` : "–"],
              ["Due", inv.due_date ? longDate(inv.due_date) : "on issue"],
              ["Received", inr(inv.received_paise)],
              ["Outstanding", inr(inv.outstanding_paise)],
            ]}
          />
          <span className="flex flex-wrap gap-4 text-[13px]">
            {inv.status === "draft" || inv.status === "verified" ? (
              canEdit && (
                <button
                  type="button"
                  onClick={onEdit}
                  className="cursor-pointer border-0 bg-transparent p-0 text-link hover:underline"
                >
                  Edit draft
                </button>
              )
            ) : (
              <Link to={`/billing?mode=ar&customer=${d.customer_id}`}>Open receivable →</Link>
            )}
            {inv.status === "verified" && (
              <span className="text-muted">Any edit clears the verification.</span>
            )}
            {(inv.status === "issued" || inv.status === "sent") && (
              <span className="text-muted">
                Issued invoices are locked; corrections use a credit note.
              </span>
            )}
          </span>
        </section>
      )}
      {d.payable && (
        <section
          aria-label="Payable"
          className="flex flex-col gap-2 rounded-card border border-line p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <b className="font-semibold">
              Supplier invoice <span className="font-mono">{d.payable.number}</span>
            </b>
            <Tag tone={AP_STATUS[d.payable.status].tone} size="sm">
              {AP_STATUS[d.payable.status].label}
            </Tag>
          </div>
          <span className="text-sm">
            Step {d.payable.stage} of 7 · {STEPS[d.payable.stage - 1]} · outstanding{" "}
            {inr(d.payable.outstanding_paise)}
          </span>
          {!d.payable.match_ok && (
            <span className="text-sm text-hi">
              Three-way match:{" "}
              {d.payable.match
                .filter((m) => !m.ok)
                .map((m) => m.text)
                .join("; ")}
            </span>
          )}
        </section>
      )}
      <KV
        items={[
          ["Reference", d.row.reference ?? "–"],
          [sale ? "Customer" : "Supplier", d.row.company],
          [sale ? "Product" : "Material", d.item ?? "–"],
          [
            "Billing",
            d.billing_basis === "consolidated" ? "When fully dispatched" : "Per dispatch",
          ],
          [sale ? "Ship date" : "Expected", d.ship_date ? longDate(d.ship_date) : "–"],
          [
            "Payment terms",
            d.payment_terms_days ? `${d.payment_terms_days} days` : "Customer's terms",
          ],
          ["Contact", d.contact ?? "–"],
          ["Created", longDate(d.created_at)],
        ]}
      />
      {d.cancelled_reason && <p className="m-0 text-sm text-hi">Cancelled: {d.cancelled_reason}</p>}
      <section className="flex flex-col gap-2">
        <h3 className="m-0 text-sm font-semibold">Commercial timeline</h3>
        {d.activity.slice(0, 5).map((a, i) => (
          <span key={i} className="flex items-start gap-2 text-[13px]">
            <span
              aria-hidden
              className={cn(
                "mt-1.5 size-2 shrink-0 rounded-full",
                a.direction === "incoming"
                  ? "bg-bl"
                  : a.direction === "outgoing"
                    ? "bg-ok"
                    : "bg-faint",
              )}
            />
            <span>
              {a.title} <span className="text-muted">· {generatedLabel(a.at)}</span>
            </span>
          </span>
        ))}
        <button
          type="button"
          onClick={onActivity}
          className="cursor-pointer self-start border-0 bg-transparent p-0 text-[13px] text-link hover:underline"
        >
          View full activity →
        </button>
      </section>
    </div>
  );
}

function Activity({ d }: { d: DealDetail }) {
  const [dir, setDir] = useState<Dir>("all");
  return (
    <div className="flex flex-col gap-3">
      <FilterChips<Dir>
        label="Activity direction"
        value={dir}
        onChange={setDir}
        options={(["all", "incoming", "outgoing", "internal"] as const).map((k) => ({
          value: k,
          label: k === "all" ? "All" : k[0]!.toUpperCase() + k.slice(1),
        }))}
      />
      <ol className="m-0 flex list-none flex-col gap-0 border-l border-line p-0 pl-4">
        {d.activity
          .filter((a) => dir === "all" || a.direction === dir)
          .map((a, i) => (
            <li key={i} className="relative flex items-start justify-between gap-3 py-2.5 text-sm">
              <span
                aria-hidden
                className={cn(
                  "absolute top-3.5 -left-[21px] size-2.5 rounded-full border-2 border-card",
                  a.direction === "incoming"
                    ? "bg-bl"
                    : a.direction === "outgoing"
                      ? "bg-ok"
                      : "bg-faint",
                )}
              />
              <span className="flex flex-col">
                <span className={a.milestone ? "font-semibold" : undefined}>{a.title}</span>
                <span className="text-xs text-muted">
                  {generatedLabel(a.at)}
                  {a.by ? ` · ${a.by}` : ""} · {a.source}
                </span>
              </span>
              <Tag tone={DIR_TONE[a.direction]} size="sm">
                {a.direction[0]!.toUpperCase() + a.direction.slice(1)}
              </Tag>
            </li>
          ))}
      </ol>
    </div>
  );
}

function DraftDialog({ d, onClose }: { d: DealDetail; onClose: () => void }) {
  const act = useBillingAction<DealDetail>();
  const { toast } = useToast();
  const inv = d.invoice!;
  const [q, setQ] = useState(String(Number(inv.quantity ?? 0)));
  const [rate, setRate] = useState(String((inv.rate_paise ?? 0) / 100));
  const [other, setOther] = useState(String(inv.other_charges_paise / 100));
  const [terms, setTerms] = useState(String(inv.payment_terms_days ?? 30));
  const [err, setErr] = useState<string | null>(null);
  const max = Number(d.dispatched_qty ?? 0);
  const ok = Number(q) > 0 && Number(q) <= max && Number(rate) > 0 && Number(other) >= 0;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Edit invoice draft"
      description={`Up to the ${qty(max, d.unit)} dispatched. Saving clears any verification.`}
      width={460}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button
            disabled={!ok || act.isPending}
            onClick={async () => {
              setErr(null);
              try {
                await act.mutateAsync(async () =>
                  unwrap(
                    await api.PATCH("/api/billing/deals/{deal_id}/invoice", {
                      params: { path: { deal_id: d.row.id } },
                      body: {
                        quantity: q,
                        rate_paise: Math.round(Number(rate) * 100),
                        other_charges_paise: Math.round(Number(other) * 100),
                        payment_terms_days: Number(terms),
                      },
                    }),
                  ),
                );
                toast({ title: "Draft updated", tone: "success" });
                onClose();
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Couldn't save.");
              }
            }}
          >
            Save draft
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className={lbl}>
          Quantity ({d.unit})
          <input
            className={field}
            inputMode="decimal"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Rate (₹ per {d.unit})
          <input
            className={field}
            inputMode="decimal"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Other charges (₹)
          <input
            className={field}
            inputMode="decimal"
            value={other}
            onChange={(e) => setOther(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Payment terms (days)
          <input
            className={field}
            inputMode="numeric"
            value={terms}
            onChange={(e) => setTerms(e.target.value)}
          />
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

function SendDialog({ d, onClose }: { d: DealDetail; onClose: () => void }) {
  const act = useBillingAction<DealDetail>();
  const { toast } = useToast();
  const [channel, setChannel] = useState<"email" | "whatsapp">("email");
  const [contact, setContact] = useState(d.contact ?? "");
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Share ${d.invoice?.number}`}
      description="Records that the invoice was shared (sending through email / WhatsApp comes with those integrations)."
      width={420}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button
            disabled={act.isPending}
            onClick={async () => {
              try {
                await act.mutateAsync(async () =>
                  unwrap(
                    await api.POST("/api/billing/deals/{deal_id}/invoice/send", {
                      params: { path: { deal_id: d.row.id } },
                      body: { channel, contact: contact.trim() || null },
                    }),
                  ),
                );
                toast({ title: "Marked as sent", tone: "success" });
                onClose();
              } catch (e) {
                toast({
                  title: e instanceof ApiError ? e.message : "Couldn't save.",
                  tone: "error",
                });
              }
            }}
          >
            Mark sent
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className={lbl}>
          Sent by
          <select
            className={field}
            value={channel}
            onChange={(e) => setChannel(e.target.value as typeof channel)}
          >
            <option value="email">Email</option>
            <option value="whatsapp">WhatsApp</option>
          </select>
        </label>
        <label className={lbl}>
          To
          <input className={field} value={contact} onChange={(e) => setContact(e.target.value)} />
        </label>
      </div>
    </Modal>
  );
}

function InteractionDialog({ d, onClose }: { d: DealDetail; onClose: () => void }) {
  const act = useBillingAction<unknown>();
  const { toast } = useToast();
  const [channel, setChannel] = useState<"call" | "whatsapp" | "email" | "visit" | "meeting">(
    "call",
  );
  const [direction, setDirection] = useState<"incoming" | "outgoing">("outgoing");
  const [contact, setContact] = useState(d.contact ?? "");
  const [summary, setSummary] = useState("");
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Add interaction · ${d.row.number}`}
      width={460}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Back
          </Button>
          <Button
            disabled={!summary.trim() || act.isPending}
            onClick={async () => {
              try {
                await act.mutateAsync(async () =>
                  unwrap(
                    await api.POST("/api/billing/deals/{deal_id}/interactions", {
                      params: { path: { deal_id: d.row.id } },
                      body: {
                        channel,
                        direction,
                        contact: contact.trim() || null,
                        summary: summary.trim(),
                      },
                    }),
                  ),
                );
                toast({ title: "Interaction logged", tone: "success" });
                onClose();
              } catch (e) {
                toast({
                  title: e instanceof ApiError ? e.message : "Couldn't save.",
                  tone: "error",
                });
              }
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
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
          Direction
          <select
            className={field}
            value={direction}
            onChange={(e) => setDirection(e.target.value as typeof direction)}
          >
            <option value="outgoing">Outgoing</option>
            <option value="incoming">Incoming</option>
          </select>
        </label>
        <label className={`${lbl} sm:col-span-2`}>
          Contact
          <input className={field} value={contact} onChange={(e) => setContact(e.target.value)} />
        </label>
        <label className={`${lbl} sm:col-span-2`}>
          Summary
          <textarea
            rows={3}
            className={field}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
          />
        </label>
      </div>
    </Modal>
  );
}
