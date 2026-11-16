import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { Button } from "@/components/ui/Button";
import { SearchBox } from "@/components/ui/Field";
import { Tooltip } from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { LoadingState } from "@/components/ui/Skeleton";
import { StatGrid } from "@/components/ui/StatGrid";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { longDate } from "@/lib/format";
import {
  DEAL_TONE,
  inr,
  months,
  useBillingAction,
  useDeals,
  type DealDetail,
  type DealRow,
} from "./api";
import { field, lbl } from "./ArDrawer";
import { DealDrawer } from "./DealDrawer";

const select =
  "cursor-pointer rounded-full border border-line-input bg-white px-3.5 py-2 text-[13px] font-medium text-ink-2";
const DOT: Record<string, string> = { incoming: "bg-bl", outgoing: "bg-ok", internal: "bg-faint" };

/** Invoice / E-bill: one row per deal (TXN-####), the commercial memory of the company. */
export function EbillTab() {
  const [params, setParams] = useSearchParams();
  const month = params.get("dmonth") ?? "all";
  const open = params.get("deal");
  const setOpen = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("deal", id);
    else next.delete("deal");
    setParams(next);
  };
  const deals = useDeals(month);
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("all");
  const [company, setCompany] = useState("all");
  const [creating, setCreating] = useState<"sale" | "purchase" | null>(null);
  const [menu, setMenu] = useState(false);
  const d = deals.data;
  const rows = (d?.rows ?? []).filter(
    (r) =>
      (kind === "all" || r.kind === kind) &&
      (status === "all"
        ? !r.archived
        : status === "Archived"
          ? r.archived
          : r.status === status && !r.archived) &&
      (company === "all" || r.company === company) &&
      (!q.trim() ||
        `${r.name} ${r.number} ${r.company} ${r.reference ?? ""}`
          .toLowerCase()
          .includes(q.trim().toLowerCase())),
  );
  const col = createColumnHelper<DealRow>();
  const columns = [
    col.accessor("name", {
      id: "deal",
      header: "Deal / order",
      meta: { label: "Deal / order", alwaysVisible: true },
      cell: (c) => (
        <span className="flex flex-col">
          <b className="font-semibold">{c.getValue()}</b>
          <span className="font-mono text-xs text-muted">
            {c.row.original.number}
            {c.row.original.provisional ? " · provisional" : ""}
          </span>
        </span>
      ),
    }),
    col.accessor("company", {
      id: "company",
      header: "Company",
      meta: { label: "Company" },
      cell: (c) => <span className="text-link">{c.getValue()}</span>,
    }),
    col.accessor("kind", {
      id: "type",
      header: "Type",
      meta: { label: "Type" },
      cell: (c) => (
        <Tag tone={c.getValue() === "sale" ? "bl" : "md"} size="sm">
          {c.getValue() === "sale" ? "Sale" : "Purchase"}
        </Tag>
      ),
    }),
    col.accessor("documents", {
      id: "documents",
      header: "Documents",
      meta: { label: "Documents" },
      cell: (c) => (
        <span className="rounded-lg border border-line px-2 py-0.5 text-[13px]">
          ▤ {c.getValue()}
        </span>
      ),
    }),
    col.accessor((r) => r.latest_at ?? "", {
      id: "latest",
      header: "Latest activity",
      meta: { label: "Latest activity" },
      cell: (c) => (
        <span className="flex max-w-[230px] items-start gap-2">
          <span
            aria-hidden
            className={cn(
              "mt-1.5 size-2 shrink-0 rounded-full",
              DOT[c.row.original.latest_direction ?? "internal"],
            )}
          />
          <span className="flex min-w-0 flex-col">
            <span className="truncate">{c.row.original.latest_activity ?? "–"}</span>
            {c.row.original.latest_at && (
              <span className="text-xs text-muted">{longDate(c.row.original.latest_at)}</span>
            )}
          </span>
        </span>
      ),
    }),
    col.accessor((r) => r.value_paise ?? -1, {
      id: "value",
      header: "Value",
      meta: { label: "Value", align: "right" },
      cell: (c) =>
        c.row.original.value_paise == null ? (
          "—"
        ) : (
          <b className="font-semibold">{inr(c.row.original.value_paise)}</b>
        ),
    }),
    col.accessor("status", {
      id: "status",
      header: "Status",
      meta: { label: "Status" },
      cell: (c) => (
        <Tag tone={DEAL_TONE[c.getValue()] ?? "lo"} size="sm">
          {c.getValue()}
        </Tag>
      ),
    }),
  ];
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h2 className="m-0 text-[26px] font-semibold tracking-[-0.01em]">Invoice / E-bill</h2>
          <p className="m-0 text-[15px] text-muted">
            Deal-wise commercial tracker for quotations, orders, invoices and all related documents.
          </p>
        </div>
        <div className="relative flex flex-wrap gap-2.5">
          <Tooltip content="Document intake and the review queue come in the next round.">
            <span>
              <Button variant="pill" disabled>
                Review queue
              </Button>
            </span>
          </Tooltip>
          <Tooltip content="Uploading documents to a deal comes in the next round.">
            <span>
              <Button variant="pill" disabled>
                Add document
              </Button>
            </span>
          </Tooltip>
          {can("billing.write") && (
            <Button
              variant="dark"
              aria-haspopup="menu"
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              Create deal ▾
            </Button>
          )}
          {menu && (
            <div
              role="menu"
              className="absolute top-12 right-0 z-10 flex w-44 flex-col rounded-xl border border-line bg-white p-1.5 shadow-modal"
            >
              {(["sale", "purchase"] as const).map((k) => (
                <button
                  key={k}
                  role="menuitem"
                  type="button"
                  onClick={() => {
                    setCreating(k);
                    setMenu(false);
                  }}
                  className="cursor-pointer rounded-lg border-0 bg-transparent px-3 py-2 text-left text-sm hover:bg-surface-2"
                >
                  {k === "sale" ? "Sale deal" : "Purchase deal"}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <StatGrid
        loading={deals.isLoading}
        items={
          d
            ? [
                {
                  label: "Active deals",
                  value: d.kpis.active,
                  caption: `of ${d.kpis.total} ${month === "all" ? "in all months" : "this month"}`,
                },
                {
                  label: "Awaiting response",
                  value: d.kpis.awaiting_response,
                  tone: "md",
                  caption: "quotations and negotiations",
                },
                {
                  label: "Documents received",
                  value: d.kpis.documents_received,
                  tone: "bl",
                  caption: "incoming documents",
                },
                {
                  label: "Invoices issued",
                  value: d.kpis.invoices_issued,
                  tone: "ok",
                  caption: "sales invoices",
                },
              ]
            : []
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox
          label="Search deals"
          placeholder="Search by deal, company, order no..."
          value={q}
          onChange={setQ}
          width={300}
        />
        <select
          aria-label="Type"
          className={select}
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="all">Type: All</option>
          <option value="sale">Sale</option>
          <option value="purchase">Purchase</option>
        </select>
        <select
          aria-label="Status"
          className={select}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">Status: All</option>
          {(d?.statuses ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
          <option value="Archived">Archived</option>
        </select>
        <select
          aria-label="Company"
          className={select}
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        >
          <option value="all">Company: All</option>
          {(d?.companies ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          aria-label="Month"
          className={select}
          value={month}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            if (e.target.value === "all") next.delete("dmonth");
            else next.set("dmonth", e.target.value);
            setParams(next);
          }}
        >
          <option value="all">All months</option>
          {months().map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>
      {deals.isLoading || !d ? (
        <LoadingState label="Loading deals" />
      ) : (
        <DataTable<DealRow>
          tableId="billing-deals"
          title="Deals"
          columns={columns}
          data={rows}
          getRowId={(r) => r.id}
          onRowClick={(r) => setOpen(r.id)}
          empty={{
            title: "No deals",
            description:
              "Deals appear for every order and purchase order, or start one with Create deal.",
          }}
        />
      )}
      {open && <DealDrawer dealId={open} onClose={() => setOpen(null)} />}
      {creating && (
        <CreateDealDialog
          kind={creating}
          onClose={() => setCreating(null)}
          onCreated={(id) => setOpen(id)}
        />
      )}
    </div>
  );
}

function CreateDealDialog({
  kind,
  onClose,
  onCreated,
}: {
  kind: "sale" | "purchase";
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const act = useBillingAction<DealDetail>();
  const { toast } = useToast();
  const [company, setCompany] = useState("");
  const [item, setItem] = useState("");
  const [reference, setReference] = useState("");
  const [qty, setQty] = useState("");
  const [unit, setUnit] = useState(kind === "sale" ? "pcs" : "t");
  const [value, setValue] = useState("");
  const [terms, setTerms] = useState("");
  const [contact, setContact] = useState("");
  const [note, setNote] = useState("");
  const [warning, setWarning] = useState<string | null>(null);
  const [existing, setExisting] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const save = async (force: boolean) => {
    setErr(null);
    try {
      const d = await act.mutateAsync(async () =>
        unwrap(
          await api.POST("/api/billing/deals", {
            body: {
              kind,
              company: company.trim(),
              item: item.trim(),
              reference: reference.trim() || null,
              quantity: qty || null,
              unit: unit || null,
              expected_value_paise: value ? Math.round(Number(value) * 100) : null,
              payment_terms_days: terms ? Number(terms) : null,
              contact: contact.trim() || null,
              note: note.trim() || null,
              force,
            },
          }),
        ),
      );
      toast({ title: `${d.row.number} created`, tone: "success" });
      onClose();
      onCreated(d.row.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const det = (e.details ?? {}) as { deal_id?: string; warning?: boolean };
        setExisting(det.deal_id ?? null);
        if (det.warning) setWarning(e.message);
        else setErr(e.message);
      } else setErr(e instanceof ApiError ? e.message : "Couldn't create the deal.");
    }
  };
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={kind === "sale" ? "New sale deal" : "New purchase deal"}
      description="Without an order or PO yet it is provisional; it keeps its Deal ID when the order is created."
      width={540}
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          {existing && (
            <Button
              variant="pill"
              onClick={() => {
                onClose();
                onCreated(existing);
              }}
            >
              Open existing
            </Button>
          )}
          {warning ? (
            <Button disabled={act.isPending} onClick={() => save(true)}>
              Create anyway
            </Button>
          ) : (
            <Button
              disabled={!company.trim() || !item.trim() || act.isPending}
              onClick={() => save(false)}
            >
              Create deal
            </Button>
          )}
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className={`${lbl} sm:col-span-2`}>
          {kind === "sale" ? "Customer" : "Supplier"}{" "}
          <span className="font-normal text-subtle">(existing)</span>
          <input className={field} value={company} onChange={(e) => setCompany(e.target.value)} />
        </label>
        <label className={lbl}>
          {kind === "sale" ? "Product" : "Item"}
          <input className={field} value={item} onChange={(e) => setItem(e.target.value)} />
        </label>
        <label className={lbl}>
          Reference <span className="font-normal text-subtle">(enquiry no., optional)</span>
          <input
            className={field}
            value={reference}
            onChange={(e) => setReference(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Quantity
          <input
            className={field}
            inputMode="decimal"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
        </label>
        <label className={lbl}>
          Unit
          <input className={field} value={unit} onChange={(e) => setUnit(e.target.value)} />
        </label>
        <label className={lbl}>
          Expected value (₹)
          <input
            className={field}
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
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
        <label className={lbl}>
          Contact
          <input className={field} value={contact} onChange={(e) => setContact(e.target.value)} />
        </label>
        <label className={lbl}>
          Note
          <input className={field} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {(warning || err) && (
          <p
            role="alert"
            className={cn("m-0 text-sm sm:col-span-2", warning ? "text-md" : "text-hi")}
          >
            {warning ?? err}
          </p>
        )}
      </div>
    </Modal>
  );
}
