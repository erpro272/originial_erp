import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { Button } from "@/components/ui/Button";
import { SearchBox } from "@/components/ui/Field";
import { FilterChips } from "@/components/ui/FilterChips";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { LoadingState } from "@/components/ui/Skeleton";
import { StatGrid } from "@/components/ui/StatGrid";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { longDate, shortDate } from "@/lib/format";
import {
  AP_STATUS,
  AR_STATUS,
  downloadCsv,
  inr,
  months,
  usePayables,
  useReceivables,
  type ApRow,
  type ArRow,
} from "./api";
import { ApDrawer, SupplierInvoiceDialog } from "./ApDrawer";
import { ArDrawer } from "./ArDrawer";

const select =
  "cursor-pointer rounded-full border border-line-input bg-white px-3.5 py-2 text-[13px] font-medium text-ink-2";

/** Payments & Settlements: what customers owe (receivables) and what we owe suppliers (payables), as of any
 * month. Every number is computed by the server from invoices, receipts and payments. */
export function PaymentsTab() {
  const [params, setParams] = useSearchParams();
  const mode = params.get("mode") === "ap" ? "ap" : "ar";
  const month = params.get("month") ?? undefined;
  const open = params.get(mode === "ar" ? "customer" : "supplier");
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next);
  };
  const { toast } = useToast();
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const opts = months();
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <SegmentedControl
          label="Receivables or payables"
          value={mode}
          onChange={(v) => {
            setStatus("all");
            set({ mode: v, customer: null, supplier: null });
          }}
          options={[
            { value: "ar", label: "↓ Accounts Receivables" },
            { value: "ap", label: "↑ Accounts Payables" },
          ]}
        />
        <AsOf mode={mode} month={month} />
      </div>
      {mode === "ar" ? <ArCards month={month} /> : <ApCards month={month} />}
      <Toolbar
        mode={mode}
        month={month ?? opts[0]!.value}
        months={opts}
        onMonth={(m) => set({ month: m === opts[0]!.value ? null : m })}
        q={q}
        onQ={setQ}
        onExport={async () => {
          try {
            await downloadCsv(mode, month, status, q);
          } catch {
            toast({ title: "Couldn't export.", tone: "error" });
          }
        }}
      />
      {mode === "ar" ? (
        <ArTable
          month={month}
          status={status}
          onStatus={setStatus}
          q={q}
          onOpen={(id) => set({ customer: id })}
        />
      ) : (
        <ApTable
          month={month}
          status={status}
          onStatus={setStatus}
          q={q}
          onOpen={(id) => set({ supplier: id })}
        />
      )}
      {open && mode === "ar" && (
        <ArDrawer
          customerId={open}
          month={month}
          onClose={() => set({ customer: null, invoice: null })}
        />
      )}
      {open && mode === "ap" && (
        <ApDrawer
          supplierId={open}
          month={month}
          onClose={() => set({ supplier: null, invoice: null })}
        />
      )}
    </div>
  );
}

function AsOf({ mode, month }: { mode: "ar" | "ap"; month: string | undefined }) {
  const ar = useReceivables(month);
  const ap = usePayables(month);
  const p = mode === "ar" ? ar.data?.period : ap.data?.period;
  return p ? <span className="text-[13px] text-muted">As of {longDate(p.as_of)}</span> : null;
}

function Toolbar({
  mode,
  month,
  months: opts,
  onMonth,
  q,
  onQ,
  onExport,
}: {
  mode: "ar" | "ap";
  month: string;
  months: { value: string; label: string }[];
  onMonth: (m: string) => void;
  q: string;
  onQ: (q: string) => void;
  onExport: () => void;
}) {
  const { can } = useAuth();
  const [adding, setAdding] = useState(false);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <select
          aria-label="Period"
          className={select}
          value={month}
          onChange={(e) => onMonth(e.target.value)}
        >
          {opts.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <SearchBox
          label={mode === "ar" ? "Search customers" : "Search suppliers"}
          placeholder={
            mode === "ar"
              ? "Search customer, GSTIN, invoice, phone"
              : "Search supplier, invoice, PO, GRN"
          }
          value={q}
          onChange={onQ}
          width={320}
        />
      </div>
      <div className="flex gap-2.5">
        {mode === "ap" && can("billing.write") && (
          <Button variant="pill" onClick={() => setAdding(true)}>
            + Supplier invoice
          </Button>
        )}
        <Button variant="pill" onClick={onExport}>
          ⤓ Export
        </Button>
      </div>
      {adding && <SupplierInvoiceDialog onClose={() => setAdding(false)} />}
    </div>
  );
}

function ArCards({ month }: { month: string | undefined }) {
  const ar = useReceivables(month);
  const c = ar.data?.cards;
  return (
    <StatGrid
      loading={ar.isLoading}
      items={
        c
          ? [
              {
                label: "Total Receivables",
                value: inr(c.total_paise),
                caption: `${c.total_customers} customers · ${c.total_invoices} invoices`,
              },
              {
                label: "Overdue",
                value: inr(c.overdue_paise),
                tone: c.overdue_paise ? "hi" : "ink",
                caption: `${c.overdue_customers} customers${c.oldest_overdue_days ? ` · oldest ${c.oldest_overdue_days} days` : ""}`,
              },
              {
                label: "Expected This Week",
                value: inr(c.expected_week_paise),
                tone: "bl",
                caption: `Promised or due ${shortDate(c.week_from)} – ${shortDate(c.week_to)}`,
              },
              {
                label: "Received This Month",
                value: inr(c.received_paise),
                tone: "ok",
                caption: `${c.receipts} receipts`,
              },
            ]
          : []
      }
    />
  );
}

function ApCards({ month }: { month: string | undefined }) {
  const ap = usePayables(month);
  const c = ap.data?.cards;
  return (
    <StatGrid
      loading={ap.isLoading}
      items={
        c
          ? [
              {
                label: "Total Payables",
                value: inr(c.total_paise),
                caption: `${c.total_suppliers} suppliers · ${c.total_invoices} invoices`,
              },
              {
                label: "Overdue",
                value: inr(c.overdue_paise),
                tone: c.overdue_paise ? "hi" : "ink",
                caption: `${c.overdue_suppliers} suppliers`,
              },
              {
                label: "Due This Week",
                value: inr(c.due_week_paise),
                tone: "md",
                caption: `Due ${shortDate(c.week_from)} – ${shortDate(c.week_to)}`,
              },
              {
                label: "Paid This Month",
                value: inr(c.paid_paise),
                tone: "ok",
                caption: `${c.payments} payments sent`,
              },
            ]
          : []
      }
    />
  );
}

function matches(text: string, q: string) {
  return !q.trim() || text.toLowerCase().includes(q.trim().toLowerCase());
}

function ArTable({
  month,
  status,
  onStatus,
  q,
  onOpen,
}: {
  month: string | undefined;
  status: string;
  onStatus: (s: string) => void;
  q: string;
  onOpen: (id: string) => void;
}) {
  const ar = useReceivables(month);
  const d = ar.data;
  if (ar.isLoading || !d) return <LoadingState label="Loading receivables" />;
  const rows = d.rows.filter(
    (r) =>
      (status === "all" ||
        (status === "part_paid"
          ? r.part_paid
          : status === "promise"
            ? r.has_promise
            : r.status === status)) &&
      matches(`${r.name} ${r.gstin ?? ""} ${r.phone ?? ""}`, q),
  );
  const col = createColumnHelper<ArRow>();
  const columns = [
    col.accessor("name", {
      id: "customer",
      header: "Customer",
      meta: { label: "Customer", alwaysVisible: true },
      cell: (c) => (
        <span className="flex flex-col">
          <b className="font-semibold">{c.getValue()}</b>
          <span className="font-mono text-xs text-muted">{c.row.original.gstin ?? "no GSTIN"}</span>
        </span>
      ),
    }),
    col.accessor("outstanding_paise", {
      id: "outstanding",
      header: "Outstanding",
      meta: { label: "Outstanding", align: "right" },
      cell: (c) => (
        <span className="flex flex-col items-end">
          <b className="font-semibold">{inr(c.getValue())}</b>
          <span className="text-xs text-muted">
            {c.row.original.open_invoices} open invoice
            {c.row.original.open_invoices === 1 ? "" : "s"}
          </span>
        </span>
      ),
    }),
    col.accessor("earliest_due", {
      id: "due",
      header: "Due date",
      meta: { label: "Due date" },
      cell: (c) => (
        <span className="flex flex-col">
          {c.getValue() ? longDate(c.getValue()!) : "–"}
          {c.row.original.days_overdue > 0 && (
            <span className="text-xs text-hi">{c.row.original.days_overdue} days overdue</span>
          )}
        </span>
      ),
    }),
    col.accessor("status", {
      id: "status",
      header: "Payment status",
      meta: { label: "Payment status" },
      cell: (c) => (
        <span className="flex flex-wrap gap-1.5">
          <Tag tone={AR_STATUS[c.getValue()].tone} size="sm">
            {AR_STATUS[c.getValue()].label}
          </Tag>
          {c.row.original.part_paid && (
            <Tag tone="lo" size="sm">
              Part-paid
            </Tag>
          )}
        </span>
      ),
    }),
    col.accessor("latest_update", {
      id: "latest",
      header: "Latest update",
      meta: { label: "Latest update" },
      cell: (c) => (
        <span className="flex max-w-[320px] flex-col">
          <span className="truncate">{c.getValue() ?? "–"}</span>
          {c.row.original.latest_at && (
            <span className="text-xs text-muted">{longDate(c.row.original.latest_at)}</span>
          )}
        </span>
      ),
    }),
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-muted">Status</span>
        <FilterChips
          label="Payment status"
          value={status}
          onChange={onStatus}
          options={[
            { value: "all", label: "All", count: d.counts.all },
            { value: "overdue", label: "Overdue", count: d.counts.overdue },
            { value: "due_week", label: "Due This Week", count: d.counts.due_week },
            { value: "promise", label: "Promise Made", count: d.counts.promise },
            { value: "part_paid", label: "Partially Paid", count: d.counts.part_paid },
          ]}
        />
      </div>
      <DataTable<ArRow>
        tableId="billing-receivables"
        title="Customer receivables"
        columns={columns}
        data={rows}
        getRowId={(r) => r.customer_id}
        onRowClick={(r) => onOpen(r.customer_id)}
        empty={{
          title: "Nothing outstanding",
          description: "No customer owes anything as of this date.",
        }}
      />
    </div>
  );
}

function ApTable({
  month,
  status,
  onStatus,
  q,
  onOpen,
}: {
  month: string | undefined;
  status: string;
  onStatus: (s: string) => void;
  q: string;
  onOpen: (id: string) => void;
}) {
  const ap = usePayables(month);
  const d = ap.data;
  if (ap.isLoading || !d) return <LoadingState label="Loading payables" />;
  const rows = d.rows.filter(
    (r) =>
      (status === "all" ||
        (status === "overdue"
          ? r.overdue
          : status === "due_week"
            ? r.due_week
            : r.statuses.includes(status as ApRow["statuses"][number]))) &&
      matches(r.name, q),
  );
  const col = createColumnHelper<ApRow>();
  const columns = [
    col.accessor("name", {
      id: "supplier",
      header: "Supplier",
      meta: { label: "Supplier", alwaysVisible: true },
      cell: (c) => <b className="font-semibold">{c.getValue()}</b>,
    }),
    col.accessor("outstanding_paise", {
      id: "outstanding",
      header: "Outstanding",
      meta: { label: "Outstanding", align: "right" },
      cell: (c) => (
        <span className="flex flex-col items-end">
          <b className="font-semibold">{inr(c.getValue())}</b>
          <span className="text-xs text-muted">
            {c.row.original.invoices} invoice{c.row.original.invoices === 1 ? "" : "s"}
            {c.row.original.disputed_paise
              ? ` · ${inr(c.row.original.disputed_paise)} disputed`
              : ""}
          </span>
        </span>
      ),
    }),
    col.accessor("earliest_due", {
      id: "due",
      header: "Due date",
      meta: { label: "Due date" },
      cell: (c) => (
        <span className="flex flex-col">
          {c.getValue() ? longDate(c.getValue()!) : "–"}
          {c.row.original.days_overdue > 0 && (
            <span className="text-xs text-hi">{c.row.original.days_overdue} days overdue</span>
          )}
        </span>
      ),
    }),
    col.accessor((r) => r.statuses.join(" "), {
      id: "status",
      header: "Approval / payment status",
      meta: { label: "Approval / payment status" },
      cell: (c) => (
        <span className="flex flex-wrap gap-1.5">
          {c.row.original.overdue && (
            <Tag tone="hi" size="sm">
              Overdue
            </Tag>
          )}
          {c.row.original.statuses.map((s) => (
            <Tag key={s} tone={AP_STATUS[s].tone} size="sm">
              {AP_STATUS[s].label}
            </Tag>
          ))}
        </span>
      ),
    }),
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-muted">Status</span>
        <FilterChips
          label="Payable status"
          value={status}
          onChange={onStatus}
          options={[
            { value: "all", label: "All", count: d.counts.all },
            { value: "overdue", label: "Overdue", count: d.counts.overdue },
            { value: "due_week", label: "Due This Week", count: d.counts.due_week },
            {
              value: "pending_verif",
              label: "Pending Verification",
              count: d.counts.pending_verif,
            },
            {
              value: "pending_owner",
              label: "Pending Owner Approval",
              count: d.counts.pending_owner,
            },
            { value: "scheduled", label: "Scheduled", count: d.counts.scheduled },
          ]}
        />
      </div>
      <DataTable<ApRow>
        tableId="billing-payables"
        title="Supplier payables"
        columns={columns}
        data={rows}
        getRowId={(r) => r.supplier_id}
        onRowClick={(r) => onOpen(r.supplier_id)}
        empty={{
          title: "Nothing to pay",
          description: "Supplier invoices appear here once they are entered.",
        }}
      />
    </div>
  );
}
