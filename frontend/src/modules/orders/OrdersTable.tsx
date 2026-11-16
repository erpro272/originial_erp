import { createColumnHelper, type SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DealChip } from "@/modules/billing/DealChip";
import { useDealRefs } from "@/modules/billing/api";
import { ApiError, api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { Button, Caret } from "@/components/ui/Button";
import { SearchBox, TextField } from "@/components/ui/Field";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Tag, toneText, type TagTone } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { useDebounced } from "@/lib/useDebounced";
import { longDate, qty, rupees, shortDate } from "@/lib/format";
import {
  fetchOrders,
  useCustomerOptions,
  useInvalidateOrders,
  useOrders,
  type Order,
  type OrderQuery,
} from "./api";
import { activeFilterCount, EMPTY_FILTERS, useSavedViews, type OrderFilters } from "./views";

const PAGE = 25;
const h = createColumnHelper<Order>();
const PRIORITY_TONE: Record<Order["priority"], TagTone> = { high: "hi", medium: "md", low: "lo" };
const PRIORITY_LABEL: Record<Order["priority"], string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};
const STATUS_FILTERS = [
  { value: "behind", label: "Behind schedule" },
  { value: "material_short", label: "Material short" },
  { value: "waiting", label: "Waiting on material" },
  { value: "new", label: "New" },
  { value: "accepted", label: "Accepted" },
  { value: "planned", label: "Planned" },
  { value: "in_production", label: "In production" },
  { value: "completed", label: "Completed" },
  { value: "shipped", label: "Shipped" },
  { value: "cancelled", label: "Cancelled" },
];
const SORT_IDS: Record<string, OrderQuery["sort"]> = {
  number: "number", customer: "customer", product: "product", quantity: "quantity", sales: "sales",
  profit: "profit", margin: "margin", processing_days: "processing_days", ship_date: "ship_date",
  priority: "priority", status: "status", created: "created",
}; // prettier-ignore

function toQuery(f: OrderFilters, sorting: SortingState, offset: number, limit = PAGE): OrderQuery {
  const s = sorting[0];
  return {
    scope: f.scope,
    customer_id: f.customer_id.length ? f.customer_id : undefined,
    priority: f.priority.length ? f.priority : undefined,
    status: f.status.length ? f.status : undefined,
    q: f.q.trim() || undefined,
    max_processing_days: f.max_processing_days ?? undefined,
    ship_from: f.ship_from || undefined,
    ship_to: f.ship_to || undefined,
    created_from: f.created_from || undefined,
    created_to: f.created_to || undefined,
    sort: s ? SORT_IDS[s.id] : "ship_date",
    desc: s?.desc ?? false,
    limit,
    offset,
  };
}

export function OrdersTable({ onOpen }: { onOpen: (o: Order) => void }) {
  const { can } = useAuth();
  const { toast } = useToast();
  const invalidate = useInvalidateOrders();
  const customers = useCustomerOptions();
  const views = useSavedViews();
  const [filters, setFilters] = useState<OrderFilters>(EMPTY_FILTERS);
  // `?q=ORD-1046` (links from the Dashboard) opens the table searched for that order
  const [params] = useSearchParams();
  const linkedQ = params.get("q");
  const [search, setSearch] = useState(linkedQ ?? "");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [activeView, setActiveView] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [appliedDefault, setAppliedDefault] = useState(false);
  const q = useDebounced(search);

  // Apply the user's default view once it has loaded (state adjusted during render, no effect).
  if (views.loaded && !appliedDefault) {
    setAppliedDefault(true);
    const v = linkedQ ? undefined : views.views.find((x) => x.id === views.defaultId);
    if (v) {
      setFilters({ ...EMPTY_FILTERS, ...v.filters });
      setSearch(v.filters.q ?? "");
      setActiveView(v.id);
    }
  }

  const effective = { ...filters, q };
  const query = toQuery(effective, sorting, offset);
  const orders = useOrders(query);
  const refs = useDealRefs(
    "order",
    (orders.data?.items ?? []).map((o) => o.id),
    can("billing.read"),
  );

  const update = (patch: Partial<OrderFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setOffset(0);
    setActiveView(null);
  };

  const columns = useMemo(
    () => [
      h.accessor("number", {
        id: "number",
        header: "Order",
        meta: { label: "Order", mono: true, alwaysVisible: true },
      }),
      h.accessor("customer_name", {
        id: "customer",
        header: "Customer",
        meta: { label: "Customer" },
      }),
      h.accessor("product_name", { id: "product", header: "Product", meta: { label: "Product" } }),
      h.accessor("priority", {
        id: "priority",
        header: "Priority",
        cell: (c) => <Tag tone={PRIORITY_TONE[c.getValue()]}>{PRIORITY_LABEL[c.getValue()]}</Tag>,
        meta: { label: "Priority" },
      }),
      h.accessor("sales_paise", {
        id: "sales",
        header: "Sales (₹)",
        cell: (c) => rupees(c.getValue()),
        meta: { label: "Sales (₹)", align: "right", csv: (o) => o.sales_paise / 100 },
      }),
      h.accessor("profit_paise", {
        id: "profit",
        header: "Profit (₹)",
        cell: (c) => rupees(c.getValue()),
        meta: { label: "Profit (₹)", align: "right", csv: (o) => o.profit_paise / 100 },
      }),
      h.accessor("ship_date", {
        id: "ship_date",
        header: "Ships",
        cell: (c) => shortDate(c.getValue()),
        meta: { label: "Ships" },
      }),
      h.accessor((o) => o.signal.label, {
        id: "status",
        header: "Status",
        // As in the mockup, only problems are coloured; normal statuses stay plain.
        cell: (c) => {
          const t = c.row.original.signal.tone;
          return (
            <span className={t === "hi" || t === "md" ? toneText[t] : undefined}>
              {c.getValue()}
            </span>
          );
        },
        meta: { label: "Status" },
      }),
      h.accessor("quantity", {
        id: "quantity",
        header: "Quantity",
        cell: (c) => `${qty(c.getValue())} ${c.row.original.unit}`,
        meta: {
          label: "Quantity",
          align: "right",
          defaultHidden: true,
          csv: (o) => Number(o.quantity),
        },
      }),
      h.accessor("margin_pct", {
        id: "margin",
        header: "Margin",
        cell: (c) => (c.getValue() === null ? "—" : `${c.getValue()}%`),
        meta: { label: "Margin", align: "right", defaultHidden: true },
      }),
      h.accessor("processing_days", {
        id: "processing_days",
        header: "Processing",
        cell: (c) => `${c.getValue()} days`,
        meta: { label: "Processing time", align: "right", defaultHidden: true },
      }),
      h.accessor("customer_phone", {
        id: "phone",
        header: "Phone",
        enableSorting: false,
        meta: { label: "Phone", defaultHidden: true },
      }),
      h.accessor("customer_email", {
        id: "email",
        header: "Email",
        enableSorting: false,
        meta: { label: "Email", defaultHidden: true },
      }),
      h.accessor("materials_summary", {
        id: "inventory",
        header: "Inventory used",
        enableSorting: false,
        cell: (c) => c.getValue() ?? "—",
        meta: { label: "Inventory used", defaultHidden: true },
      }),
      h.accessor("created_at", {
        id: "created",
        header: "Created",
        cell: (c) => longDate(c.getValue()),
        meta: { label: "Created", defaultHidden: true },
      }),
      h.display({
        id: "deal",
        header: "Deal",
        cell: (c) => <DealChip deal={refs.data?.[c.row.original.id]} />,
        meta: { label: "Deal (Billing)" },
      }),
      h.accessor((o) => o.plan?.number ?? "", {
        id: "planning",
        header: "Plan",
        enableSorting: false,
        cell: (c) => <PlanTag order={c.row.original} />,
        meta: {
          label: "Plan",
          csv: (o) => o.plan?.number ?? (o.marked_for_planning ? "In planning" : ""),
        },
      }),
    ],
    [refs.data],
  );

  const selection = async (marked: boolean) => {
    try {
      const r = unwrap(
        await api.POST("/api/orders/planning-selection", { body: { order_ids: selected, marked } }),
      );
      toast({
        title: !marked
          ? `${r.updated} removed from Planning`
          : r.plan
            ? r.created
              ? `${r.plan.number} started with ${r.updated} order${r.updated === 1 ? "" : "s"}`
              : `${r.updated} added to ${r.plan.number}`
            : `${r.updated} sent to Planning`,
        tone: "success",
      });
      setSelected([]);
      await invalidate();
    } catch (e) {
      toast({
        title: "Couldn't update",
        description: e instanceof ApiError ? e.message : undefined,
        tone: "error",
      });
    }
  };

  const nFilters = activeFilterCount(filters);
  const viewName = views.views.find((v) => v.id === activeView)?.name;

  return (
    <>
      <DataTable<Order>
        tableId="orders"
        title="All orders received"
        columns={columns}
        data={orders.data?.items ?? []}
        getRowId={(o) => o.id}
        loading={orders.isPending}
        error={orders.isError ? (orders.error as Error).message : null}
        onRetry={() => orders.refetch()}
        onRowClick={onOpen}
        sorting={{ state: sorting, onChange: (s) => (setSorting(s), setOffset(0)) }}
        pagination={{ total: orders.data?.total ?? 0, limit: PAGE, offset, onChange: setOffset }}
        empty={{
          title: filters.scope === "past" ? "No past orders match" : "No open orders match",
          description: nFilters || q ? "Try removing some filters." : undefined,
        }}
        selection={
          can("orders.write") && filters.scope === "current"
            ? { selected, onChange: setSelected, label: (o) => o.number }
            : undefined
        }
        csv={{
          filename: `orders-${filters.scope}.csv`,
          fetchAll: async () => (await fetchOrders(toQuery(effective, sorting, 0, 1000))).items,
        }}
        actions={
          <>
            <SegmentedControl
              size="sm"
              label="Current or past orders"
              value={filters.scope}
              onChange={(scope) => (update({ scope }), setSelected([]))}
              options={[
                { value: "current", label: "Current" },
                { value: "past", label: "Past" },
              ]}
            />
            <MultiSelect
              label="Customers"
              allLabel="All customers"
              options={(customers.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
              value={filters.customer_id}
              onChange={(customer_id) => update({ customer_id })}
            />
            <MultiSelect
              label="Priority"
              allLabel="Priority"
              searchable={false}
              options={[
                { value: "high", label: "High" },
                { value: "medium", label: "Medium" },
                { value: "low", label: "Low" },
              ]}
              value={filters.priority}
              onChange={(priority) => update({ priority })}
            />
            <MultiSelect
              label="Status"
              allLabel="Status"
              searchable={false}
              options={STATUS_FILTERS}
              value={filters.status}
              onChange={(status) => update({ status })}
            />
            <MoreFilters filters={filters} onChange={update} />
            <Menu>
              <MenuTrigger asChild>
                <Button variant="pill" aria-label="Saved views">
                  {viewName ? `View: ${viewName}` : "Views"} <Caret />
                </Button>
              </MenuTrigger>
              <MenuContent>
                {views.views.length > 0 && <MenuLabel>Saved views</MenuLabel>}
                {views.views.map((v) => (
                  <MenuItem
                    key={v.id}
                    onSelect={() => {
                      setFilters({ ...EMPTY_FILTERS, ...v.filters });
                      setSearch(v.filters.q ?? "");
                      setActiveView(v.id);
                      setOffset(0);
                    }}
                  >
                    <span className="flex-1">{v.name}</span>
                    {views.defaultId === v.id && (
                      <Tag tone="lo" size="sm">
                        default
                      </Tag>
                    )}
                  </MenuItem>
                ))}
                {views.views.length > 0 && <MenuSeparator />}
                <MenuItem onSelect={() => setSaveOpen(true)}>
                  Save current filters as a view…
                </MenuItem>
                {activeView && (
                  <>
                    <MenuItem
                      onSelect={() =>
                        views.setDefault(views.defaultId === activeView ? null : activeView)
                      }
                    >
                      {views.defaultId === activeView
                        ? "Stop opening this view by default"
                        : "Open this view by default"}
                    </MenuItem>
                    <MenuItem
                      onSelect={() => (views.remove(activeView), setActiveView(null))}
                      className="text-hi"
                    >
                      Delete this view
                    </MenuItem>
                  </>
                )}
                {(nFilters > 0 || q) && (
                  <MenuItem
                    onSelect={() => (
                      setFilters({ ...EMPTY_FILTERS, scope: filters.scope }),
                      setSearch(""),
                      setActiveView(null)
                    )}
                  >
                    Clear all filters
                  </MenuItem>
                )}
              </MenuContent>
            </Menu>
            <SearchBox
              label="Search orders"
              placeholder="Search orders"
              value={search}
              onChange={(v) => (setSearch(v), setOffset(0))}
            />
          </>
        }
        toolbar={
          selected.length > 0 && (
            <div className="flex flex-wrap items-center gap-3 border-t border-divider bg-surface-blue px-5 py-2.5 text-sm">
              <b>{selected.length} selected</b>
              <Button size="sm" onClick={() => selection(true)}>
                Send to Planning
              </Button>
              <Button size="sm" variant="pill" onClick={() => selection(false)}>
                Remove from Planning
              </Button>
              <button
                type="button"
                className="cursor-pointer border-0 bg-transparent text-link"
                onClick={() => setSelected([])}
              >
                Clear
              </button>
            </div>
          )
        }
      />
      {saveOpen && (
        <SaveViewModal
          onClose={() => setSaveOpen(false)}
          onSave={(name, asDefault) => {
            const v = views.add(name, { ...filters, q });
            if (asDefault) views.setDefault(v.id);
            setActiveView(v.id);
            setSaveOpen(false);
            toast({ title: `View "${name}" saved`, tone: "success" });
          }}
        />
      )}
    </>
  );
}

function MoreFilters({
  filters,
  onChange,
}: {
  filters: OrderFilters;
  onChange: (p: Partial<OrderFilters>) => void;
}) {
  const n =
    (filters.max_processing_days ? 1 : 0) +
    (filters.ship_from || filters.ship_to ? 1 : 0) +
    (filters.created_from || filters.created_to ? 1 : 0);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="pill" className={cn(n && "border-faint text-ink")}>
          Filters{n ? ` (${n})` : ""} <Caret />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="grid w-80 gap-3">
        <TextField
          label="Processing time under (days)"
          type="number"
          min={1}
          value={filters.max_processing_days ?? ""}
          onChange={(e) =>
            onChange({ max_processing_days: e.target.value ? Number(e.target.value) : null })
          }
        />
        <div className="grid grid-cols-2 gap-2">
          <TextField
            label="Ships from"
            type="date"
            value={filters.ship_from}
            onChange={(e) => onChange({ ship_from: e.target.value })}
          />
          <TextField
            label="Ships to"
            type="date"
            value={filters.ship_to}
            onChange={(e) => onChange({ ship_to: e.target.value })}
          />
          <TextField
            label="Created from"
            type="date"
            value={filters.created_from}
            onChange={(e) => onChange({ created_from: e.target.value })}
          />
          <TextField
            label="Created to"
            type="date"
            value={filters.created_to}
            onChange={(e) => onChange({ created_to: e.target.value })}
          />
        </div>
        {n > 0 && (
          <button
            type="button"
            className="cursor-pointer justify-self-start border-0 bg-transparent text-[13px] font-medium text-link"
            onClick={() =>
              onChange({
                max_processing_days: null,
                ship_from: "",
                ship_to: "",
                created_from: "",
                created_to: "",
              })
            }
          >
            Clear these filters
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}

function SaveViewModal({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (name: string, asDefault: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [asDefault, setAsDefault] = useState(false);
  const valid = name.trim().length >= 2;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Save view"
      description="Saves the current filters and search so you can open them again in one click."
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!valid} onClick={() => onSave(name, asDefault)}>
            Save view
          </Button>
        </>
      }
    >
      <TextField
        label="Name"
        placeholder="e.g. Key accounts, under 5 days"
        value={name}
        onChange={(e) => setName(e.target.value)}
        autoFocus
      />
      <label className="flex items-center gap-2.5 text-sm text-ink-2">
        <input
          type="checkbox"
          className="size-4"
          checked={asDefault}
          onChange={(e) => setAsDefault(e.target.checked)}
        />
        Open this view by default
      </label>
    </Modal>
  );
}

/** Which plan an order is in: the active plan (being planned) or an approved / finished one. */
function PlanTag({ order }: { order: Order }) {
  const p = order.plan;
  if (!p) return order.marked_for_planning ? <Tag tone="bl">In planning</Tag> : null;
  const active = p.stage === "draft" || p.stage === "awaiting";
  const tone = active
    ? "bl"
    : p.stage === "needs_reapproval"
      ? "hi"
      : p.stage === "approved"
        ? "ok"
        : "lo";
  return (
    <Link
      to={active ? "/planning" : `/planning/${p.id}`}
      onClick={(e) => e.stopPropagation()}
      className="no-underline"
    >
      <Tag tone={tone}>{active ? `In ${p.number}` : p.number}</Tag>
    </Link>
  );
}
