import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { PageActions } from "@/components/layout/PageActions";
import { Button } from "@/components/ui/Button";
import { SearchBox } from "@/components/ui/Field";
import { KpiStrip } from "@/components/ui/KpiStrip";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { UnderlineTabs } from "@/components/ui/Tabs";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { rupeesCompact, shortDate } from "@/lib/format";
import {
  PRIORITY,
  STAGE,
  STATUS,
  qtyText,
  useComparison,
  useInventory,
  usePurchases,
  type Inventory,
  type MaterialRow,
  type Po,
} from "./api";
import { PoActionDialog, RaisePoDialog } from "./PoDialogs";
import { ApproveButton, PurchaseTab } from "./PurchaseTab";
import { RequestQuoteDialog, SupplierTab } from "./SupplierTab";

type StatusKey = keyof typeof STATUS;
const select =
  "cursor-pointer rounded-full border border-line-input bg-white px-3.5 py-2 text-[13px] font-medium text-ink-2";

/** Purchasing: raw material stock levels, shortage alerts and open purchase orders. */
export function PurchasingPage() {
  const { can } = useAuth();
  const inv = useInventory();
  const { pathname } = useLocation();
  const [raising, setRaising] = useState<MaterialRow | null | "new">(null);
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState<"all" | StatusKey>("all");
  const [q, setQ] = useState("");
  const d = inv.data;
  const section = pathname.endsWith("/purchase")
    ? "purchase"
    : pathname.endsWith("/suppliers")
      ? "suppliers"
      : "inventory";
  const buying = section === "purchase";
  const pur = usePurchases();
  const pd = pur.data;
  const [params, setParams] = useSearchParams();
  const openPo = params.get("po");
  const setOpenPo = (id: string | null) => setParams(id ? { po: id } : {});
  const [supplier, setSupplier] = useState("all");
  const [priority, setPriority] = useState("all");
  const [stage, setStage] = useState("all");
  const [pq, setPq] = useState("");
  const comparing = section === "suppliers";
  const cmp = useComparison();
  const cd = cmp.data;
  const [material, setMaterial] = useState("all");
  const [minStars, setMinStars] = useState("0");
  const [supStatus, setSupStatus] = useState("all");
  const [sq, setSq] = useState("");
  const [quoting, setQuoting] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      {can("purchasing.write") && comparing && cd && (
        <PageActions>
          <Button onClick={() => setQuoting(true)}>+ Request Quote</Button>
        </PageActions>
      )}
      {can("purchasing.write") && !comparing && d && (
        <PageActions>
          <Button onClick={() => setRaising("new")}>{buying ? "+ New PO" : "+ Raise PO"}</Button>
        </PageActions>
      )}
      <div className="flex flex-wrap items-start justify-between gap-5">
        <PageHeader
          title="Purchasing"
          subtitle={
            comparing
              ? "Compare supplier pricing, lead times, on-time delivery, and quality ratings."
              : buying
                ? "Manage raw material purchase orders, approvals, and incoming deliveries."
                : "Track raw material stock levels, shortage alerts, and open purchase orders."
          }
        />
        {buying && pd && (
          <KpiStrip
            items={[
              { label: "Open POs", value: pd.kpis.open },
              {
                label: "Pending approval",
                value: pd.kpis.pending_approval,
                tone: pd.kpis.pending_approval ? "hi" : "ink",
              },
              { label: "In transit", value: pd.kpis.in_transit, tone: "bl" },
              { label: "Open spend", value: rupeesCompact(pd.kpis.open_spend_paise), tone: "md" },
            ]}
          />
        )}
        {comparing && cd && (
          <KpiStrip
            items={[
              { label: "Open/Active vendors", value: cd.kpis.active_suppliers },
              {
                label: "Avg on-time",
                value: cd.kpis.avg_on_time_pct == null ? "–" : `${cd.kpis.avg_on_time_pct}%`,
                tone: "ok",
              },
              {
                label: "Avg lead time",
                value: cd.kpis.avg_lead_days == null ? "–" : `${cd.kpis.avg_lead_days} days`,
                tone: "bl",
              },
              {
                label: "Saved (30d)",
                value: rupeesCompact(cd.kpis.saved_30d_paise),
                tone: cd.kpis.saved_30d_paise < 0 ? "hi" : "md",
              },
            ]}
          />
        )}
        {!buying && !comparing && d && (
          <KpiStrip
            items={[
              { label: "Total SKUs", value: d.kpis.skus },
              {
                label: "Below reorder",
                value: d.kpis.below_reorder,
                tone: d.kpis.below_reorder ? "hi" : "ink",
              },
              { label: "On order", value: d.kpis.on_order, tone: "bl" },
              { label: "Stock value", value: rupeesCompact(d.kpis.stock_value_paise), tone: "md" },
            ]}
          />
        )}
      </div>
      <UnderlineTabs
        label="Purchasing sections"
        tabs={[
          { to: "/purchasing", label: "Inventory", count: d?.kpis.skus, end: true },
          { to: "/purchasing/purchase", label: "Raw Material Purchase", count: pd?.kpis.open },
          {
            to: "/purchasing/suppliers",
            label: "Supplier Comparison",
            count: cd?.kpis.active_suppliers,
          },
        ]}
        right={
          section === "inventory" && d ? (
            <>
              <select
                aria-label="Category"
                className={select}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="all">All categories</option>
                {d.categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <select
                aria-label="Status"
                className={select}
                value={status}
                onChange={(e) => setStatus(e.target.value as typeof status)}
              >
                <option value="all">Status: all</option>
                {(Object.keys(STATUS) as StatusKey[]).map((s) => (
                  <option key={s} value={s}>
                    {STATUS[s].label}
                  </option>
                ))}
              </select>
              <SearchBox
                label="Search materials"
                placeholder="Search materials"
                value={q}
                onChange={setQ}
                width={170}
              />
            </>
          ) : comparing && cd ? (
            <>
              <select
                aria-label="Material"
                className={select}
                value={material}
                onChange={(e) => setMaterial(e.target.value)}
              >
                <option value="all">All materials</option>
                {cd.materials.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
              <select
                aria-label="Rating"
                className={select}
                value={minStars}
                onChange={(e) => setMinStars(e.target.value)}
              >
                <option value="0">Rating: all</option>
                <option value="4">4★ and up</option>
                <option value="3">3★ and up</option>
              </select>
              <select
                aria-label="Status"
                className={select}
                value={supStatus}
                onChange={(e) => setSupStatus(e.target.value)}
              >
                <option value="all">Status: all</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
                <option value="risk">At risk</option>
                <option value="new">No history yet</option>
              </select>
              <SearchBox
                label="Search suppliers"
                placeholder="Search suppliers"
                value={sq}
                onChange={setSq}
                width={160}
              />
            </>
          ) : buying && pd ? (
            <>
              <select
                aria-label="Supplier"
                className={select}
                value={supplier}
                onChange={(e) => setSupplier(e.target.value)}
              >
                <option value="all">All suppliers</option>
                {pd.suppliers.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
              <select
                aria-label="Priority"
                className={select}
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
              >
                <option value="all">Priority: all</option>
                {(Object.keys(PRIORITY) as (keyof typeof PRIORITY)[]).map((x) => (
                  <option key={x} value={x}>
                    {PRIORITY[x].label}
                  </option>
                ))}
              </select>
              <select
                aria-label="Status"
                className={select}
                value={stage}
                onChange={(e) => setStage(e.target.value)}
              >
                <option value="all">Status: all</option>
                {(Object.keys(STAGE) as Po["stage"][]).map((x) => (
                  <option key={x} value={x}>
                    {STAGE[x].label}
                  </option>
                ))}
              </select>
              <SearchBox
                label="Search POs"
                placeholder="Search POs"
                value={pq}
                onChange={setPq}
                width={160}
              />
            </>
          ) : undefined
        }
      />
      {buying ? (
        pur.isLoading || !pd ? (
          <LoadingState label="Loading purchase orders" />
        ) : (
          <PurchaseTab
            d={pd}
            open={openPo}
            onOpen={setOpenPo}
            rows={pd.purchase_orders.filter(
              (r) =>
                (supplier === "all" || r.supplier === supplier) &&
                (priority === "all" || r.priority === priority) &&
                (stage === "all" || r.stage === stage) &&
                (!pq.trim() ||
                  `${r.number} ${r.supplier} ${r.lines[0]?.material ?? ""} ${r.orders.join(" ")}`
                    .toLowerCase()
                    .includes(pq.trim().toLowerCase())),
            )}
          />
        )
      ) : comparing ? (
        cmp.isLoading || !cd ? (
          <LoadingState label="Loading suppliers" />
        ) : (
          <SupplierTab
            d={cd}
            materialId={material === "all" ? null : material}
            rows={cd.rows.filter(
              (r) =>
                (material === "all" || r.material_id === material) &&
                r.stars >= Number(minStars) &&
                (supStatus === "all" ||
                  (supStatus === "active" && r.active) ||
                  (supStatus === "inactive" && !r.active) ||
                  (supStatus === "risk" && r.flags.some((f) => f.endsWith("risk"))) ||
                  (supStatus === "new" && r.flags.includes("No history yet"))) &&
                (!sq.trim() ||
                  `${r.supplier} ${r.material} ${r.code}`
                    .toLowerCase()
                    .includes(sq.trim().toLowerCase())),
            )}
          />
        )
      ) : inv.isLoading || !d ? (
        <LoadingState label="Loading inventory" />
      ) : (
        <InventoryTab
          d={d}
          rows={d.materials.filter(
            (m) =>
              (category === "all" || m.category === category) &&
              (status === "all" || m.status === status) &&
              (!q.trim() ||
                `${m.code} ${m.name} ${m.grade ?? ""}`
                  .toLowerCase()
                  .includes(q.trim().toLowerCase())),
          )}
          onRaise={(m) => setRaising(m)}
        />
      )}
      {quoting && cd && <RequestQuoteDialog d={cd} onClose={() => setQuoting(false)} />}
      {raising && d && (
        <RaisePoDialog
          inventory={d}
          material={raising === "new" ? null : raising}
          onClose={() => setRaising(null)}
        />
      )}
    </div>
  );
}

function InventoryTab({
  d,
  rows,
  onRaise,
}: {
  d: Inventory;
  rows: MaterialRow[];
  onRaise: (m: MaterialRow) => void;
}) {
  const { can } = useAuth();
  const write = can("purchasing.write");
  const col = createColumnHelper<MaterialRow>();
  const columns = [
    col.accessor("name", {
      id: "material",
      header: "Material",
      meta: { label: "Material", alwaysVisible: true },
      cell: (c) => (
        <span className="flex flex-col">
          <span>{c.getValue()}</span>
          <small className="font-mono text-xs text-subtle">{c.row.original.code}</small>
        </span>
      ),
    }),
    col.accessor((r) => r.grade ?? "–", {
      id: "grade",
      header: "Grade / spec",
      meta: { label: "Grade / spec" },
    }),
    col.accessor((r) => Number(r.in_stock), {
      id: "in_stock",
      header: "In stock",
      meta: { label: "In stock" },
      cell: (c) => qtyText(c.row.original.in_stock, c.row.original.unit),
    }),
    col.accessor((r) => Number(r.reserved), {
      id: "reserved",
      header: "Reserved",
      meta: { label: "Reserved" },
      cell: (c) =>
        Number(c.row.original.reserved)
          ? qtyText(c.row.original.reserved, c.row.original.unit)
          : "—",
    }),
    col.accessor((r) => Number(r.on_order), {
      id: "on_order",
      header: "On order",
      meta: { label: "On order" },
      cell: (c) =>
        Number(c.row.original.on_order)
          ? qtyText(c.row.original.on_order, c.row.original.unit)
          : "—",
    }),
    col.accessor((r) => Number(r.reorder_level), {
      id: "reorder",
      header: "Reorder level",
      meta: { label: "Reorder level" },
      cell: (c) => qtyText(c.row.original.reorder_level, c.row.original.unit),
    }),
    col.accessor("status", {
      id: "status",
      header: "Status",
      meta: { label: "Status" },
      cell: (c) => (
        <Tag tone={STATUS[c.getValue()].tone} size="sm">
          {STATUS[c.getValue()].label}
        </Tag>
      ),
    }),
    col.accessor((r) => r.category ?? "–", {
      id: "category",
      header: "Category",
      meta: { label: "Category", defaultHidden: true },
    }),
    col.accessor((r) => Number(r.free), {
      id: "free",
      header: "Free",
      meta: { label: "Free (in stock − reserved)", defaultHidden: true },
      cell: (c) => qtyText(c.row.original.free, c.row.original.unit),
    }),
    col.accessor("stock_value_paise", {
      id: "value",
      header: "Stock value",
      meta: { label: "Stock value", align: "right", defaultHidden: true },
      cell: (c) => rupeesCompact(c.getValue()),
    }),
  ];

  return (
    <>
      {d.attention.length > 0 && (
        <section aria-label="Needs attention" className="flex flex-col gap-3">
          <h3 className="m-0 text-xs font-semibold tracking-[0.06em] text-muted uppercase">
            Needs attention
          </h3>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {d.attention.map((m) => (
              <AttentionCard key={m.id} m={m} canRaise={write} onRaise={() => onRaise(m)} />
            ))}
          </div>
        </section>
      )}
      <DataTable<MaterialRow>
        tableId="purchasing-inventory"
        title="Raw material stock & PO status"
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        empty={{
          title: "No materials match",
          description: "Change the category, status or search.",
        }}
      />
      <OpenPurchaseOrders pos={d.purchase_orders} />
    </>
  );
}

function AttentionCard({
  m,
  canRaise,
  onRaise,
}: {
  m: MaterialRow;
  canRaise: boolean;
  onRaise: () => void;
}) {
  const s = STATUS[m.status];
  const first = m.incoming.find((i) => i.status !== "awaiting_approval");
  const waiting = m.incoming.find((i) => i.status === "awaiting_approval");
  return (
    <article
      data-testid={`attention-${m.code}`}
      className={cn(
        "flex flex-col gap-1.5 rounded-card border bg-white p-[18px]",
        m.status === "critical_short"
          ? "border-hi-line"
          : m.status === "low_stock"
            ? "border-md-line"
            : "border-line",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-muted">{m.code}</span>
        <Tag tone={s.tone} size="sm">
          {s.label}
        </Tag>
      </div>
      <b className="text-[15px]">
        {m.code} · {m.name}
        {m.grade ? ` (${m.grade})` : ""}
      </b>
      <span className="text-[13px] text-ink-2">
        Current: {qtyText(m.in_stock, m.unit)} ·{" "}
        {m.status === "in_transit" && first
          ? `Incoming: ${qtyText(first.quantity, m.unit)}`
          : `Min: ${qtyText(m.reorder_level, m.unit)}`}
      </span>
      <span className={cn("text-[13px]", m.status === "critical_short" ? "text-hi" : "text-ink-2")}>
        {m.reason}
      </span>
      <div className="mt-2 flex min-h-9 items-center justify-between gap-2 border-t border-divider pt-3">
        {m.status === "in_transit" && first ? (
          <span className="text-[13px] text-ok">
            {first.po_number} {first.confirmed ? "confirmed" : "ordered"}
          </span>
        ) : waiting ? (
          <span className="text-[13px] text-md">{waiting.po_number} awaiting approval</span>
        ) : (
          <span />
        )}
        {canRaise && m.status !== "in_transit" && !waiting && (
          <Button variant="dark" size="sm" onClick={onRaise}>
            Raise PO
          </Button>
        )}
      </div>
    </article>
  );
}

function OpenPurchaseOrders({ pos }: { pos: Po[] }) {
  const { can } = useAuth();
  const [cancelling, setCancelling] = useState<Po | null>(null);
  const write = can("purchasing.write");
  const btn = "cursor-pointer border-0 bg-transparent p-0 text-[13px] text-link hover:underline";
  return (
    <section
      aria-label="Open purchase orders"
      className="overflow-hidden rounded-card border border-line"
    >
      <div className="flex items-center justify-between px-5 py-4">
        <h3 className="m-0 text-[17px] font-semibold">Open purchase orders</h3>
        <span className="text-[13px] text-muted">
          Raised → owner approves → sent → dispatched → gate entry → QC → in stock
        </span>
      </div>
      {pos.length === 0 ? (
        <p className="m-0 border-t border-divider px-5 py-6 text-sm text-muted">
          No open purchase orders.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <thead>
              <tr className="bg-surface text-left text-xs font-semibold tracking-[0.04em] text-muted uppercase">
                {["PO", "Material", "Supplier", "Quantity", "Value", "Expected", "Status", ""].map(
                  (h) => (
                    <th key={h} className="border-t border-divider px-5 py-3 font-semibold">
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {pos.map((po) => {
                const ln = po.lines[0];
                const st = STAGE[po.stage];
                return (
                  <tr key={po.id} data-testid={`po-${po.number}`}>
                    <td className="border-t border-divider px-5 py-3 font-mono font-semibold">
                      {po.number}
                    </td>
                    <td className="border-t border-divider px-5 py-3">
                      {ln ? `${ln.code} · ${ln.material}` : "–"}
                    </td>
                    <td className="border-t border-divider px-5 py-3">{po.supplier}</td>
                    <td className="border-t border-divider px-5 py-3">
                      {ln
                        ? Number(ln.received_qty)
                          ? `${qtyText(ln.received_qty, ln.unit)} of ${qtyText(ln.quantity, ln.unit)}`
                          : qtyText(ln.quantity, ln.unit)
                        : "–"}
                    </td>
                    <td className="border-t border-divider px-5 py-3">
                      {rupeesCompact(po.value_paise)}
                    </td>
                    <td className="border-t border-divider px-5 py-3">
                      {shortDate(po.expected_date)}
                      {po.confirmed && (
                        <small className="ml-1 text-xs text-subtle">confirmed</small>
                      )}
                    </td>
                    <td className="border-t border-divider px-5 py-3">
                      <Tag tone={st.tone} size="sm">
                        {st.label}
                      </Tag>
                    </td>
                    <td className="border-t border-divider px-5 py-3">
                      <span className="flex items-center justify-end gap-4">
                        {po.status === "awaiting_approval" && <ApproveButton po={po} />}
                        <Link to={`/purchasing/purchase?po=${po.id}`} className={btn}>
                          Manage →
                        </Link>
                        {write &&
                          po.status !== "at_gate" &&
                          Number(ln?.received_qty ?? 0) === 0 && (
                            <button
                              type="button"
                              className={cn(btn, "text-hi")}
                              onClick={() => setCancelling(po)}
                            >
                              Cancel
                            </button>
                          )}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {cancelling && (
        <PoActionDialog po={cancelling} action="cancel" onClose={() => setCancelling(null)} />
      )}
    </section>
  );
}
