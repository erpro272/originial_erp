import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button, Caret, buttonVariants } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { SelectField, TextAreaField, TextField } from "@/components/ui/Field";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { LoadingState } from "@/components/ui/Skeleton";
import { StatGrid } from "@/components/ui/StatGrid";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { longDate, qty, rupees, rupeesCompact, shortDate } from "@/lib/format";
import { STATES } from "@/lib/gst";
import { fetchOrders, ORDER_STATUS_LABEL, useCustomerOptions } from "../orders/api";
import { InvoiceViewModal } from "../invoices/InvoiceViewModal";
import { HEALTH, useCustomer, type CustomerDetail } from "./api";
import { CustomerFormModal } from "./CustomerFormModal";
import { last12Months, MonthlySalesChart } from "./MonthlySalesChart";
import { PeriodButton, usePeriod } from "./period";

const digits = (s: string | null | undefined) => (s ?? "").replace(/\D/g, "");
const KIND_LABEL = {
  call: "Call",
  whatsapp: "WhatsApp",
  email: "Email",
  note: "Note",
  reminder: "Reminder",
} as const;

export function CustomerProfile() {
  const { id = "" } = useParams();
  const period = usePeriod();
  const q = useCustomer(id, period.query);
  const { can } = useAuth();
  const [editing, setEditing] = useState(false);
  const [merging, setMerging] = useState(false);
  const [followup, setFollowup] = useState<
    null | "call" | "whatsapp" | "email" | "note" | "reminder"
  >(null);
  const [invoice, setInvoice] = useState<string | null>(null);

  if (q.isPending) return <LoadingState label="Loading customer…" />;
  if (q.isError)
    return (
      <EmptyState
        title="Customer not found"
        description={(q.error as Error).message}
        actions={
          <Link
            to="/orders/customers"
            className={buttonVariants({ variant: "pill", size: "pill" })}
          >
            Back to customers
          </Link>
        }
      />
    );
  const c = q.data;
  const r = c.row;
  const phone = digits(r.phone);
  const wa = phone ? `https://wa.me/${phone.length === 10 ? `91${phone}` : phone}` : null;

  return (
    <>
      <Link
        to={`/orders/customers?${period.search}`}
        className="-mb-4 self-start text-sm font-medium no-underline"
      >
        ← All customers
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 flex flex-wrap items-center gap-3 text-[28px] font-bold tracking-[-0.01em]">
            {r.name}
            {r.health_tags.map((t) => (
              <Tag key={t} tone={HEALTH[t].tone}>
                {HEALTH[t].label}
              </Tag>
            ))}
          </h2>
          <span className="text-sm text-muted">
            {r.gstin && <span className="mr-3 font-mono text-ink-2">{r.gstin}</span>}
            {[r.city, r.state].filter(Boolean).join(", ")} ·{" "}
            {r.tier === "key" ? "Key account" : r.tier === "standard" ? "Standard" : "Occasional"}
            {r.primary_contact && ` · ${r.primary_contact}`}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {phone && (
            <a
              href={`tel:${phone}`}
              onClick={() => setFollowup("call")}
              className={cn(buttonVariants({ variant: "pill" }), "no-underline")}
            >
              Call
            </a>
          )}
          {wa && (
            <a
              href={wa}
              target="_blank"
              rel="noreferrer"
              onClick={() => setFollowup("whatsapp")}
              className={cn(buttonVariants({ variant: "pill" }), "no-underline")}
            >
              WhatsApp
            </a>
          )}
          {r.email && (
            <a
              href={`mailto:${r.email}`}
              onClick={() => setFollowup("email")}
              className={cn(buttonVariants({ variant: "pill" }), "no-underline")}
            >
              Email
            </a>
          )}
          <Button variant="dark" size="sm" onClick={() => setFollowup("reminder")}>
            Set reminder
          </Button>
          {can("customers.write") && (
            <Menu>
              <MenuTrigger asChild>
                <Button variant="pill" aria-label="More actions">
                  More <Caret />
                </Button>
              </MenuTrigger>
              <MenuContent>
                <MenuItem onSelect={() => setFollowup("note")}>Add note</MenuItem>
                <MenuItem onSelect={() => setEditing(true)}>Edit details</MenuItem>
                <MenuItem onSelect={() => setMerging(true)}>
                  Merge a duplicate into this customer…
                </MenuItem>
              </MenuContent>
            </Menu>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <PeriodButton />
        <span className="text-[13px] text-muted">
          Sales, invoices, AOV and units follow the period; outstanding and last purchase are as of
          today.
        </span>
      </div>
      <StatGrid
        items={[
          {
            label: "Total sales",
            value: rupeesCompact(r.total_sales_paise),
            caption:
              r.sales_change_pct == null
                ? "This period"
                : `${r.sales_change_pct > 0 ? "+" : ""}${r.sales_change_pct}% vs previous`,
          },
          { label: "Invoices", value: r.invoices, caption: `${r.lifetime_invoices} in total` },
          {
            label: "Average order value",
            value: r.aov_paise == null ? "—" : rupeesCompact(r.aov_paise),
          },
          {
            label: "Outstanding",
            value: rupeesCompact(r.outstanding_paise),
            tone: r.outstanding_paise > 0 ? "hi" : "ink",
            caption:
              r.credit_used_pct == null ? "Receivables" : `${r.credit_used_pct}% of credit limit`,
          },
          {
            label: "Last purchase",
            value: r.last_purchase ? shortDate(r.last_purchase) : "—",
            caption: r.days_since_last == null ? "Never bought" : `${r.days_since_last} days ago`,
          },
          {
            label: "Buys every",
            value: r.frequency_days == null ? "—" : `${Math.round(r.frequency_days)} days`,
            caption: "On average",
          },
        ]}
      />

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(300px,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card>
            <CardHeader title="Sales by month" suffix="last 12 months" />
            <div className="px-5 pb-4">
              <MonthlySalesChart data={c.monthly_sales} months={last12Months()} />
            </div>
          </Card>
          <InvoicesCard c={c} onOpen={setInvoice} />
          <OrdersCard customerId={r.id} />
        </div>
        <div className="flex flex-col gap-5">
          <FollowupsCard c={c} onAdd={(k) => setFollowup(k)} />
          <DetailsCard c={c} />
          {c.top_products.length > 0 && (
            <Card>
              <CardHeader title="Products bought" />
              <ul className="m-0 list-none px-5 pb-4">
                {c.top_products.map((p) => (
                  <li
                    key={p.name}
                    className="flex justify-between gap-3 border-t border-divider py-2 text-sm first:border-t-0"
                  >
                    <span>{p.name}</span>
                    <span className="text-muted tabular-nums">
                      {qty(p.quantity, 0)} {(p.uom ?? "").toLowerCase()} ·{" "}
                      {rupeesCompact(p.value_paise)}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>

      {editing && <CustomerFormModal customer={c} onClose={() => setEditing(false)} />}
      {merging && <MergeModal target={c} onClose={() => setMerging(false)} />}
      {followup && (
        <FollowupModal customerId={r.id} kind={followup} onClose={() => setFollowup(null)} />
      )}
      {invoice && <InvoiceViewModal invoiceId={invoice} onClose={() => setInvoice(null)} />}
    </>
  );
}

function InvoicesCard({ c, onOpen }: { c: CustomerDetail; onOpen: (id: string) => void }) {
  const [all, setAll] = useState(false);
  const rows = all ? c.invoices : c.invoices.slice(0, 8);
  const tone = { paid: "ok", partial: "md", unpaid: "hi" } as const;
  return (
    <Card>
      <CardHeader title="Invoices" suffix={`${c.invoices.length} in total`} />
      {c.invoices.length === 0 ? (
        <p className="m-0 px-5 pb-5 text-sm text-muted">
          No invoices yet. Upload past invoices to build this customer's history.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead className="bg-surface">
              <tr>
                {["Invoice", "Date", "Total (₹)", "Balance (₹)", "Status"].map((h, i) => (
                  <th
                    key={h}
                    className={cn(
                      "px-4 py-2.5 text-left text-xs font-semibold tracking-[.04em] text-muted uppercase",
                      i >= 2 && i <= 3 && "text-right",
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr
                  key={i.id}
                  tabIndex={0}
                  onClick={() => onOpen(i.id)}
                  onKeyDown={(e) => e.key === "Enter" && onOpen(i.id)}
                  className="cursor-pointer hover:bg-surface"
                >
                  <td className="border-t border-divider px-4 py-3 font-mono text-[13px]">
                    {i.invoice_number ?? "—"}
                  </td>
                  <td className="border-t border-divider px-4 py-3 text-sm">
                    {longDate(i.invoice_date)}
                  </td>
                  <td className="border-t border-divider px-4 py-3 text-right text-sm tabular-nums">
                    {i.grand_total_paise == null ? "—" : rupees(i.grand_total_paise)}
                  </td>
                  <td className="border-t border-divider px-4 py-3 text-right text-sm tabular-nums">
                    {rupees(i.balance_due_paise ?? 0)}
                  </td>
                  <td className="border-t border-divider px-4 py-3">
                    <Tag tone={tone[i.status as keyof typeof tone] ?? "lo"} size="sm">
                      {i.status}
                    </Tag>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {c.invoices.length > 8 && (
            <button
              type="button"
              onClick={() => setAll(!all)}
              className="w-full cursor-pointer border-0 border-t border-divider bg-transparent py-2.5 text-[13px] font-medium text-link"
            >
              {all ? "Show fewer" : `Show all ${c.invoices.length} invoices`}
            </button>
          )}
        </div>
      )}
    </Card>
  );
}

function OrdersCard({ customerId }: { customerId: string }) {
  const q = useQuery({
    queryKey: ["orders", "list", "customer", customerId],
    queryFn: () =>
      fetchOrders({
        scope: "all",
        customer_id: [customerId],
        sort: "ship_date",
        desc: true,
        limit: 10,
      }),
  });
  return (
    <Card>
      <CardHeader title="Orders" suffix={q.data ? `${q.data.total} in total` : undefined} />
      {q.isError ? (
        <ErrorState message="Couldn't load orders." onRetry={() => q.refetch()} />
      ) : !q.data ? (
        <LoadingState />
      ) : q.data.items.length === 0 ? (
        <p className="m-0 px-5 pb-5 text-sm text-muted">No orders from this customer yet.</p>
      ) : (
        <ul className="m-0 list-none px-5 pb-3">
          {q.data.items.map((o) => (
            <li
              key={o.id}
              className="flex flex-wrap items-center justify-between gap-3 border-t border-divider py-2.5 text-sm first:border-t-0"
            >
              <span>
                <span className="font-mono text-[13px] font-semibold">{o.number}</span> ·{" "}
                {o.product_name} · {qty(o.quantity)} {o.unit}
              </span>
              <span className="text-muted">
                {rupeesCompact(o.sales_paise)} · ships {shortDate(o.ship_date)} ·{" "}
                {ORDER_STATUS_LABEL[o.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function FollowupsCard({
  c,
  onAdd,
}: {
  c: CustomerDetail;
  onAdd: (k: "note" | "reminder") => void;
}) {
  const qc = useQueryClient();
  const done = async (fid: string) => {
    unwrap(
      await api.POST("/api/customers/{customer_id}/followups/{followup_id}/done", {
        params: { path: { customer_id: c.row.id, followup_id: fid } },
      }),
    );
    await qc.invalidateQueries({ queryKey: ["customers"] });
  };
  return (
    <Card>
      <CardHeader
        title="Follow-ups"
        actions={
          <>
            <Button variant="pill" onClick={() => onAdd("note")}>
              + Note
            </Button>
            <Button variant="pill" onClick={() => onAdd("reminder")}>
              + Reminder
            </Button>
          </>
        }
      />
      {c.followups.length === 0 ? (
        <p className="m-0 px-5 pb-5 text-sm text-muted">
          No follow-ups yet. Calls, WhatsApp messages and emails you start here are logged.
        </p>
      ) : (
        <ul className="m-0 list-none px-5 pb-3">
          {c.followups.map((f) => {
            const open = f.kind === "reminder" && !f.done_at;
            return (
              <li key={f.id} className="flex gap-3 border-t border-divider py-3 first:border-t-0">
                <span
                  aria-hidden
                  className={cn(
                    "mt-1.5 size-2 flex-none rounded-full",
                    open ? "bg-md-accent" : "bg-faint",
                  )}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-sm">
                  <span className="flex items-center justify-between gap-2">
                    <b className="font-semibold">
                      {KIND_LABEL[f.kind]}
                      {f.due_date && (
                        <span className={cn("font-normal", open ? "text-md" : "text-muted")}>
                          {" "}
                          · due {longDate(f.due_date)}
                        </span>
                      )}
                    </b>
                    {open && (
                      <button
                        type="button"
                        onClick={() => done(f.id)}
                        className="cursor-pointer border-0 bg-transparent text-[13px] font-medium text-link"
                      >
                        Mark done
                      </button>
                    )}
                  </span>
                  {f.note && <span className="text-ink-2">{f.note}</span>}
                  <small className="text-xs text-muted">
                    {f.created_by_name ?? "Someone"} · {longDate(f.created_at)}
                  </small>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function DetailsCard({ c }: { c: CustomerDetail }) {
  const r = c.row;
  const bill = c.addresses.find((a) => a.kind === "billing");
  const rows: [string, React.ReactNode][] = [
    ["GSTIN", r.gstin ? <span className="font-mono">{r.gstin}</span> : "—"],
    ["PAN", r.pan ? <span className="font-mono">{r.pan}</span> : "—"],
    ["State", r.state_code ? `${r.state_code} · ${STATES[r.state_code] ?? ""}` : "—"],
    ["Phone", r.phone ?? "—"],
    ["Email", r.email ?? "—"],
    [
      "Billing address",
      bill ? [bill.line1, bill.city, bill.pincode].filter(Boolean).join(", ") : "—",
    ],
    ["Payment terms", r.payment_terms_days == null ? "—" : `${r.payment_terms_days} days`],
    ["Credit limit", r.credit_limit_paise == null ? "—" : `₹${rupees(r.credit_limit_paise)}`],
    ["Bank", c.bank_name ? `${c.bank_name}${c.bank_ifsc ? ` · ${c.bank_ifsc}` : ""}` : "—"],
    ["Account no.", c.bank_account ? <span className="font-mono">{c.bank_account}</span> : "—"],
    ["UPI", c.upi_id ?? "—"],
    ["Tags", r.tags.length ? r.tags.join(", ") : "—"],
  ];
  return (
    <Card>
      <CardHeader
        title="Details"
        suffix={c.sensitive_visible ? undefined : "bank details masked for your role"}
      />
      <dl className="m-0 px-5 pb-4">
        {rows.map(([k, v]) => (
          <div
            key={k}
            className="grid grid-cols-[120px_1fr] gap-3 border-t border-divider py-2 text-sm first:border-t-0"
          >
            <dt className="text-muted">{k}</dt>
            <dd className="m-0 break-words">{v}</dd>
          </div>
        ))}
      </dl>
      {c.notes && (
        <p className="m-0 border-t border-divider px-5 py-3 text-sm text-ink-2">{c.notes}</p>
      )}
      {c.contacts.length > 1 && (
        <p className="m-0 border-t border-divider px-5 py-3 text-[13px] text-muted">
          Other contacts:{" "}
          {c.contacts
            .slice(1)
            .map((x) => x.name)
            .join(", ")}
        </p>
      )}
    </Card>
  );
}

function FollowupModal({
  customerId,
  kind,
  onClose,
}: {
  customerId: string;
  kind: "call" | "whatsapp" | "email" | "note" | "reminder";
  onClose: () => void;
}) {
  const [k, setK] = useState(kind);
  const [note, setNote] = useState("");
  const [due, setDue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();
  const { toast } = useToast();
  const save = async () => {
    if (k === "reminder" && !due) return setError("Choose when to be reminded.");
    try {
      unwrap(
        await api.POST("/api/customers/{customer_id}/followups", {
          params: { path: { customer_id: customerId } },
          body: { kind: k, note: note || null, due_date: due || null },
        }),
      );
      await qc.invalidateQueries({ queryKey: ["customers"] });
      toast({ title: k === "reminder" ? "Reminder set" : "Follow-up logged", tone: "success" });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save.");
    }
  };
  const title = {
    call: "Log the call",
    whatsapp: "Log the WhatsApp message",
    email: "Log the email",
    note: "Add a note",
    reminder: "Set a reminder",
  }[k];
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={title}
      description={
        ["call", "whatsapp", "email"].includes(kind)
          ? "Opened in your phone or mail app. Note what was agreed so the team can see it."
          : undefined
      }
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Skip
          </Button>
          <Button onClick={save}>Save</Button>
        </>
      }
    >
      <SelectField label="Type" value={k} onChange={(e) => setK(e.target.value as typeof k)}>
        {Object.entries(KIND_LABEL).map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </SelectField>
      <TextAreaField
        label="Note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. Purchase head asked for Q4 pricing"
      />
      {k === "reminder" && (
        <TextField
          label="Remind me on"
          type="date"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          error={error ?? undefined}
        />
      )}
      {error && k !== "reminder" && (
        <p role="alert" className="m-0 text-sm text-hi">
          {error}
        </p>
      )}
    </Modal>
  );
}

function MergeModal({ target, onClose }: { target: CustomerDetail; onClose: () => void }) {
  const options = useCustomerOptions();
  const [source, setSource] = useState("");
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const chosen = options.data?.find((o) => o.id === source);
  const merge = async () => {
    try {
      unwrap(
        await api.POST("/api/customers/{customer_id}/merge", {
          params: { path: { customer_id: target.row.id } },
          body: { source_id: source },
        }),
      );
      await qc.invalidateQueries({ queryKey: ["customers"] });
      await qc.invalidateQueries({ queryKey: ["orders"] });
      toast({ title: `${chosen?.name} merged into ${target.row.name}`, tone: "success" });
      onClose();
      navigate(`/orders/customers/${target.row.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't merge.");
    }
  };
  return (
    <Modal
      open
      tone="warning"
      onOpenChange={(o) => !o && onClose()}
      title={`Merge a duplicate into ${target.row.name}`}
      description="The duplicate's invoices, orders, contacts and follow-ups move here, and the duplicate record is closed. This can't be undone."
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="dark" disabled={!source} onClick={merge}>
            Merge
          </Button>
        </>
      }
    >
      <SelectField
        label="Duplicate customer"
        value={source}
        onChange={(e) => (setSource(e.target.value), setError(null))}
        error={error ?? undefined}
      >
        <option value="">Choose…</option>
        {options.data
          ?.filter((o) => o.id !== target.row.id)
          .map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
              {o.gstin ? ` · ${o.gstin}` : ""}
            </option>
          ))}
      </SelectField>
    </Modal>
  );
}
