import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, type SortingState } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { Button, Caret } from "@/components/ui/Button";
import { SectionLabel } from "@/components/ui/Card";
import { SearchBox, TextField } from "@/components/ui/Field";
import { FilterChips } from "@/components/ui/FilterChips";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Menu";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { StatGrid } from "@/components/ui/StatGrid";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { longDate, parseRupeesToPaise, qty, rupees } from "@/lib/format";
import { STATES } from "@/lib/gst";
import {
  fetchCustomers,
  HEALTH,
  HEALTH_ORDER,
  useCustomers,
  useHealthSettings,
  type CustomerQuery,
  type CustomerRow,
  type Health,
} from "./api";
import { CustomerFormModal } from "./CustomerFormModal";
import { HealthSettingsModal } from "./HealthSettingsModal";
import { PeriodButton, usePeriod } from "./period";
import { UploadInvoiceButton } from "../invoices/UploadInvoiceDialog";

const PAGE = 10;
const h = createColumnHelper<CustomerRow>();
const SORTABLE: Record<string, CustomerQuery["sort"]> = {
  name: "name", total_sales: "total_sales", invoices: "invoices", aov: "aov", units: "units",
  outstanding: "outstanding", last_purchase: "last_purchase", frequency: "frequency", health: "health",
  state: "state", created: "created",
}; // prettier-ignore

interface Filters {
  state: string[];
  tier: string[];
  product: string;
  outstanding_only: boolean;
  min_sales: string;
  max_sales: string;
  followups_due: boolean;
}
const NO_FILTERS: Filters = {
  state: [],
  tier: [],
  product: "",
  outstanding_only: false,
  min_sales: "",
  max_sales: "",
  followups_due: false,
};

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

const money = (p: number) => rupees(p);
const plainCol = (
  id: keyof CustomerRow & string,
  label: string,
  fmt?: (r: CustomerRow) => React.ReactNode,
  align?: "right",
) =>
  h.accessor((r) => (r[id] == null ? "" : String(r[id])), {
    id,
    header: label,
    enableSorting: false,
    cell: (c) => (fmt ? fmt(c.row.original) : c.getValue() || "—"),
    meta: { label, defaultHidden: true, align },
  });

export function CustomersTab() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const period = usePeriod();
  const [health, setHealth] = useState<Health | "all">("all");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [sorting, setSorting] = useState<SortingState>([{ id: "total_sales", desc: true }]);
  const [offset, setOffset] = useState(0);
  const [adding, setAdding] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const q = useDebounced(search);
  const rules = useHealthSettings();
  const reviews = useQuery({
    queryKey: ["invoices", "uploads", "summary"],
    queryFn: async () => unwrap(await api.GET("/api/invoices/uploads")).summary,
    enabled: can("invoices.write"),
    refetchInterval: (query) => ((query.state.data?.processing ?? 0) > 0 ? 3000 : false),
  });

  const needReview = reviews.data?.need_review ?? 0;
  const processing = reviews.data?.processing ?? 0;
  const sort = sorting[0];
  const build = (offset: number, limit: number): CustomerQuery => ({
    ...period.query,
    q: q.trim() || undefined,
    health: health === "all" ? undefined : [health],
    state: filters.state.length ? filters.state : undefined,
    tier: filters.tier.length ? filters.tier : undefined,
    product: filters.product.trim() || undefined,
    outstanding_only: filters.outstanding_only || undefined,
    min_sales_paise: parseRupeesToPaise(filters.min_sales) ?? undefined,
    max_sales_paise: parseRupeesToPaise(filters.max_sales) ?? undefined,
    followups_due: filters.followups_due || undefined,
    sort: sort ? SORTABLE[sort.id] : "total_sales",
    desc: sort?.desc ?? true,
    limit,
    offset,
  });
  const page = useCustomers(build(offset, PAGE));
  const d = page.data;

  const columns = useMemo(
    () => [
      h.accessor("name", {
        id: "name",
        header: "Customer",
        cell: (c) => (
          <span className="flex flex-col">
            <b className="font-semibold">{c.getValue()}</b>
            {c.row.original.gstin && (
              <span className="mt-0.5 font-mono text-xs text-muted">{c.row.original.gstin}</span>
            )}
          </span>
        ),
        meta: { label: "Customer", alwaysVisible: true, csv: (r) => r.name },
      }),
      h.accessor("total_sales_paise", {
        id: "total_sales",
        header: "Total sales (₹)",
        cell: (c) => money(c.getValue()),
        meta: { label: "Total sales (₹)", align: "right", csv: (r) => r.total_sales_paise / 100 },
      }),
      h.accessor("invoices", {
        id: "invoices",
        header: "Invoices",
        meta: { label: "Invoices", align: "right" },
      }),
      h.accessor("aov_paise", {
        id: "aov",
        header: "AOV (₹)",
        cell: (c) => (c.getValue() == null ? "—" : money(c.getValue()!)),
        meta: { label: "AOV (₹)", align: "right", csv: (r) => (r.aov_paise ?? 0) / 100 },
      }),
      h.accessor("units_sold", {
        id: "units",
        header: "Units sold",
        cell: (c) => qty(c.getValue(), 0),
        meta: { label: "Units sold (pcs)", align: "right", csv: (r) => Number(r.units_sold) },
      }),
      h.accessor("outstanding_paise", {
        id: "outstanding",
        header: "Outstanding (₹)",
        cell: (c) => (
          <span className={c.getValue() > 0 ? "text-hi" : "text-muted"}>{money(c.getValue())}</span>
        ),
        meta: { label: "Outstanding (₹)", align: "right", csv: (r) => r.outstanding_paise / 100 },
      }),
      h.accessor("last_purchase", {
        id: "last_purchase",
        header: "Last purchase",
        cell: (c) => {
          const r = c.row.original;
          const late = r.health === "inactive" || r.health === "dormant";
          return (
            <>
              {longDate(c.getValue())}
              {late && r.days_since_last != null && (
                <span className="text-xs text-hi"> · {r.days_since_last} days</span>
              )}
            </>
          );
        },
        meta: { label: "Last purchase" },
      }),
      h.accessor("health", {
        id: "health",
        header: "Health",
        cell: (c) =>
          c.getValue() ? (
            <Tag tone={HEALTH[c.getValue()!].tone}>{HEALTH[c.getValue()!].label}</Tag>
          ) : (
            <span className="text-muted">—</span>
          ),
        meta: {
          label: "Health",
          csv: (r) => r.health_tags.map((t) => HEALTH[t].label).join(" + "),
        },
      }),
      h.accessor("frequency_days", {
        id: "frequency",
        header: "Buys every",
        cell: (c) => (c.getValue() == null ? "—" : `${Math.round(c.getValue()!)} days`),
        meta: { label: "Purchase frequency", align: "right", defaultHidden: true },
      }),
      h.accessor("state", {
        id: "state",
        header: "State",
        cell: (c) => c.getValue() ?? "—",
        meta: { label: "State", defaultHidden: true },
      }),
      h.accessor("created_at", {
        id: "created",
        header: "Added",
        cell: (c) => longDate(c.getValue()),
        meta: { label: "Added on", defaultHidden: true },
      }),
      plainCol("city", "City"),
      plainCol("phone", "Phone"),
      plainCol("email", "Email"),
      plainCol("primary_contact", "Contact person"),
      plainCol("gstin", "GSTIN"),
      plainCol("pan", "PAN"),
      plainCol("tier", "Tier", (r) => r.tier[0]!.toUpperCase() + r.tier.slice(1)),
      plainCol("tags", "Tags", (r) => r.tags.join(", ") || "—"),
      plainCol("payment_terms_days", "Payment terms", (r) =>
        r.payment_terms_days == null ? "—" : `${r.payment_terms_days} days`,
      ),
      plainCol(
        "credit_limit_paise",
        "Credit limit (₹)",
        (r) => (r.credit_limit_paise == null ? "—" : money(r.credit_limit_paise)),
        "right",
      ),
      plainCol(
        "credit_used_pct",
        "Credit used",
        (r) => (r.credit_used_pct == null ? "—" : `${r.credit_used_pct}%`),
        "right",
      ),
      plainCol(
        "previous_sales_paise",
        "Previous period sales (₹)",
        (r) => money(r.previous_sales_paise),
        "right",
      ),
      plainCol(
        "sales_change_pct",
        "Change vs previous",
        (r) =>
          r.sales_change_pct == null
            ? "—"
            : `${r.sales_change_pct > 0 ? "+" : ""}${r.sales_change_pct}%`,
        "right",
      ),
      plainCol(
        "lifetime_sales_paise",
        "Lifetime sales (₹)",
        (r) => money(r.lifetime_sales_paise),
        "right",
      ),
      plainCol("lifetime_invoices", "Lifetime invoices", undefined, "right"),
      plainCol("first_purchase", "First purchase", (r) => longDate(r.first_purchase)),
      plainCol("days_since_last", "Days since last purchase", undefined, "right"),
      plainCol(
        "health_tags",
        "All health tags",
        (r) => r.health_tags.map((t) => HEALTH[t].label).join(", ") || "—",
      ),
      plainCol("open_followups", "Open reminders", undefined, "right"),
      plainCol("next_followup", "Next reminder", (r) => longDate(r.next_followup)),
      plainCol("source", "Added from", (r) =>
        r.source === "invoice" ? "Invoice upload" : "Manual",
      ),
    ],
    [],
  );

  const counts = d?.health_counts ?? {};
  const nFilters =
    filters.state.length + filters.tier.length + (filters.product ? 1 : 0) + (filters.outstanding_only ? 1 : 0) +
    (filters.min_sales || filters.max_sales ? 1 : 0) + (filters.followups_due ? 1 : 0); // prettier-ignore
  const r = rules.data;
  const set = (p: Partial<Filters>) => (setFilters((f) => ({ ...f, ...p })), setOffset(0));

  return (
    <>
      <section className="flex flex-col gap-3.5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <SectionLabel>Customer overview</SectionLabel>
            <PeriodButton range={d?.period} />
          </div>
          <div className="flex gap-2">
            {can("invoices.write") && <UploadInvoiceButton />}
            {can("customers.write") && (
              <Button variant="dark" size="sm" onClick={() => setAdding(true)}>
                + Add customer
              </Button>
            )}
          </div>
        </div>
        {needReview + processing > 0 && (
          <Link
            to="/orders/customers/imports"
            className="flex items-center justify-between rounded-xl border border-bl-line bg-surface-blue px-4 py-2.5 text-sm text-ink no-underline hover:text-ink"
          >
            <span>
              <b>
                {needReview} uploaded invoice{needReview === 1 ? "" : "s"} need
                {needReview === 1 ? "s" : ""} review
              </b>
              {processing > 0 && (
                <span className="text-muted"> · {processing} still being read</span>
              )}
            </span>
            <span className="font-medium text-link">Review →</span>
          </Link>
        )}
        <StatGrid
          loading={page.isPending}
          items={[
            {
              label: "Total customers",
              value: d?.overview.total_customers ?? "—",
              caption: "Registered",
            },
            {
              label: "Active customers",
              value: d?.overview.active_customers ?? "—",
              tone: "bl",
              caption: d ? `${d.overview.active_pct}% of total` : undefined,
            },
            {
              label: "New customers",
              value: d?.overview.new_customers ?? "—",
              tone: "ok",
              caption: "This period",
            },
            {
              label: "Units sold",
              value: d ? qty(d.overview.units_sold, 0) : "—",
              caption: "pcs · this period",
            },
          ]}
        />
      </section>

      <section className="flex flex-col gap-3.5">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <SectionLabel>Customer health</SectionLabel>
          <span className="text-[13px] text-muted">
            {r
              ? `Inactive = no order in ${r.inactive_days}–${r.dormant_days} days · Dormant = ${r.dormant_days}+ days`
              : ""}
            {can("settings.write") && (
              <button
                type="button"
                onClick={() => setRulesOpen(true)}
                className="ml-2 cursor-pointer border-0 bg-transparent font-medium text-link"
              >
                Edit rules
              </button>
            )}
          </span>
        </div>
        <FilterChips
          label="Filter by customer health"
          value={health}
          onChange={(v) => (setHealth(v), setOffset(0))}
          options={[
            { value: "all" as const, label: "All", count: counts.all },
            ...HEALTH_ORDER.map((k) => ({
              value: k,
              label: HEALTH[k].label,
              count: counts[k],
              dot: HEALTH[k].dot,
            })),
          ]}
        />
      </section>

      <DataTable<CustomerRow>
        tableId="customers"
        title="All customers"
        columns={columns}
        data={d?.items ?? []}
        getRowId={(r) => r.id}
        loading={page.isPending}
        error={page.isError ? (page.error as Error).message : null}
        onRetry={() => page.refetch()}
        onRowClick={(row) => navigate(`/orders/customers/${row.id}?${period.search}`)}
        sorting={{ state: sorting, onChange: (s) => (setSorting(s), setOffset(0)) }}
        pagination={{ total: d?.total ?? 0, limit: PAGE, offset, onChange: setOffset }}
        availableFields={d?.available_fields}
        empty={{
          title: "No customers match",
          description:
            nFilters || q || health !== "all"
              ? "Try removing some filters."
              : "Add a customer or upload invoices to get started.",
        }}
        csv={{
          filename: "customers.csv",
          fetchAll: async () => (await fetchCustomers(build(0, 1000))).items,
        }}
        actions={
          <>
            <SearchBox
              label="Search customers"
              placeholder="Search name, GSTIN, phone"
              width={190}
              value={search}
              onChange={(v) => (setSearch(v), setOffset(0))}
            />
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="pill" className={cn(nFilters && "border-faint text-ink")}>
                  Filters{nFilters ? ` (${nFilters})` : ""} <Caret />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="grid w-80 gap-3">
                <div className="flex flex-wrap gap-2">
                  <MultiSelect
                    label="State"
                    allLabel="All states"
                    options={Object.entries(STATES).map(([code, name]) => ({
                      value: code,
                      label: name,
                    }))}
                    value={filters.state}
                    onChange={(state) => set({ state })}
                  />
                  <MultiSelect
                    label="Tier"
                    allLabel="All tiers"
                    searchable={false}
                    options={[
                      { value: "key", label: "Key" },
                      { value: "standard", label: "Standard" },
                      { value: "occasional", label: "Occasional" },
                    ]}
                    value={filters.tier}
                    onChange={(tier) => set({ tier })}
                  />
                </div>
                <TextField
                  label="Bought product"
                  placeholder="e.g. M10 hex bolts"
                  value={filters.product}
                  onChange={(e) => set({ product: e.target.value })}
                />
                <div className="grid grid-cols-2 gap-2">
                  <TextField
                    label="Sales from (₹)"
                    inputMode="decimal"
                    value={filters.min_sales}
                    onChange={(e) => set({ min_sales: e.target.value })}
                  />
                  <TextField
                    label="Sales to (₹)"
                    inputMode="decimal"
                    value={filters.max_sales}
                    onChange={(e) => set({ max_sales: e.target.value })}
                  />
                </div>
                <label className="flex items-center gap-2.5 text-sm text-ink-2">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={filters.outstanding_only}
                    onChange={(e) => set({ outstanding_only: e.target.checked })}
                  />
                  Has outstanding receivables
                </label>
                <label className="flex items-center gap-2.5 text-sm text-ink-2">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={filters.followups_due}
                    onChange={(e) => set({ followups_due: e.target.checked })}
                  />
                  Follow-up reminder due
                </label>
                {nFilters > 0 && (
                  <button
                    type="button"
                    className="cursor-pointer justify-self-start border-0 bg-transparent text-[13px] font-medium text-link"
                    onClick={() => set(NO_FILTERS)}
                  >
                    Clear filters
                  </button>
                )}
              </PopoverContent>
            </Popover>
          </>
        }
      />
      {adding && (
        <CustomerFormModal
          customer={null}
          onClose={() => setAdding(false)}
          onSaved={(id) => navigate(`/orders/customers/${id}`)}
        />
      )}
      {rulesOpen && r && <HealthSettingsModal initial={r} onClose={() => setRulesOpen(false)} />}
    </>
  );
}
