import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/data-table/DataTable";
import { PageActions } from "@/components/layout/PageActions";
import { Button } from "@/components/ui/Button";
import { FilterChips } from "@/components/ui/FilterChips";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { rupeesCompact, shortDate } from "@/lib/format";
import { useCreatePlan, usePlans, type PlanSummary } from "./api";
import { DeletePlanDialog } from "./DeletePlan";
import { plural, range } from "./format";
import { DELETABLE_STATUSES, STAGES, type Stage } from "./status";

type Filter = "all" | Stage;
const ORDER: Stage[] = ["approved", "needs_reapproval", "completed", "cancelled"];

/** Plan history: every plan except the active one. Approved plans open exactly as approved (read-only);
 * a plan that needs re-approval is a revision of the same plan. */
export function PlanHistory() {
  const { can } = useAuth();
  const plans = usePlans();
  const create = useCreatePlan();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [deleting, setDeleting] = useState<PlanSummary | null>(null);
  const all = plans.data ?? [];
  const working = all.find((r) => r.stage === "draft" || r.stage === "awaiting");
  const rows = all.filter((r) => r !== working);
  const shown = filter === "all" ? rows : rows.filter((r) => r.stage === filter);

  const newPlan = async () => {
    try {
      await create.mutateAsync();
      navigate("/planning");
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't start a plan.", tone: "error" });
    }
  };

  const col = createColumnHelper<PlanSummary>();
  const columns = [
    col.accessor("number", {
      id: "plan",
      header: "Plan",
      meta: { label: "Plan", alwaysVisible: true },
      cell: (c) => <b className="font-mono font-semibold">{c.getValue()}</b>,
    }),
    col.accessor("created_at", {
      id: "created",
      header: "Created",
      meta: { label: "Created" },
      cell: (c) => shortDate(c.getValue()),
    }),
    col.accessor("orders", {
      id: "orders",
      header: "Orders",
      meta: { label: "Orders", align: "right" },
    }),
    col.accessor("stage", {
      id: "status",
      header: "Status",
      meta: { label: "Status" },
      cell: (c) => {
        const s = STAGES[c.getValue() as Stage];
        const r = c.row.original;
        return (
          <span className="flex flex-col items-start gap-1">
            <Tag tone={s.tone} size="sm">
              {r.revision ? `Rev ${r.revision} · ${s.label.toLowerCase()}` : s.label}
            </Tag>
            {r.reapproval_reason && (
              <span className="max-w-[280px] text-xs text-muted">{r.reapproval_reason}</span>
            )}
          </span>
        );
      },
    }),
    col.accessor((r) => (r.start && r.end ? range(r.start, r.end) : "–"), {
      id: "window",
      header: "Production window",
      meta: { label: "Production window" },
    }),
    col.accessor("approved_at", {
      id: "approved",
      header: "Approved",
      meta: { label: "Approved" },
      cell: (c) => {
        const r = c.row.original;
        if (!c.getValue()) return "–";
        return `${shortDate(c.getValue()!)}${r.snapshot_version && r.snapshot_version > 1 ? ` · v${r.snapshot_version}` : ""}`;
      },
    }),
    col.accessor("value", {
      id: "value",
      header: "Sales value",
      meta: { label: "Sales value", align: "right" },
      cell: (c) => rupeesCompact(c.getValue()),
    }),
    col.accessor("contribution", {
      id: "contribution",
      header: "Contribution",
      meta: { label: "Contribution", align: "right" },
      cell: (c) => <b className="text-ok">{rupeesCompact(c.getValue())}</b>,
    }),
    col.accessor("margin", {
      id: "margin",
      header: "Margin",
      meta: { label: "Margin", align: "right" },
      cell: (c) => `${c.getValue().toFixed(1)}%`,
    }),
    col.display({
      id: "actions",
      header: "",
      meta: { label: "Actions", alwaysVisible: true },
      cell: (c) => {
        const r = c.row.original;
        return can("planning.approve") && DELETABLE_STATUSES.includes(r.status) ? (
          <button
            type="button"
            aria-label={`Delete ${r.number}`}
            onClick={(e) => {
              e.stopPropagation(); // not "open the plan"
              setDeleting(r);
            }}
            className="cursor-pointer border-0 bg-transparent p-0 text-[13px] text-hi hover:underline"
          >
            Delete
          </button>
        ) : null;
      },
    }),
  ];

  return (
    <div className="flex flex-col gap-7">
      <PageActions>
        {can("planning.write") && !working && !plans.isLoading && (
          <Button onClick={newPlan} disabled={create.isPending}>
            + New plan
          </Button>
        )}
      </PageActions>
      <div className="flex flex-col gap-3">
        <Link to="/planning" className="text-[13px] no-underline">
          ← Active plan
        </Link>
        <PageHeader
          title="Plan history"
          subtitle="Previous plans with their orders, schedule, money, fixes and approval record. Approved plans open exactly as approved."
        />
      </div>
      {working && (
        <button
          type="button"
          onClick={() => navigate("/planning")}
          className="flex cursor-pointer flex-wrap items-center justify-between gap-3 rounded-card border border-bl-line bg-surface-blue px-5 py-4 text-left text-sm"
        >
          <span>
            Active plan: <b className="font-mono">{working.number}</b> ·{" "}
            {STAGES[working.stage as Stage].label.toLowerCase()} · {plural(working.orders, "order")}
          </span>
          <span className="text-link">Continue planning →</span>
        </button>
      )}
      <FilterChips<Filter>
        label="Plan status"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "All", count: rows.length },
          ...ORDER.map((s) => ({
            value: s,
            label: STAGES[s].label,
            count: rows.filter((r) => r.stage === s).length,
          })),
        ]}
      />
      {deleting && <DeletePlanDialog plan={deleting} onClose={() => setDeleting(null)} />}
      <DataTable<PlanSummary>
        tableId="planning-plans"
        title="Previous plans"
        columns={columns}
        data={shown}
        getRowId={(r) => r.id}
        loading={plans.isLoading}
        error={plans.isError ? "Couldn't load the plans." : null}
        onRetry={() => void plans.refetch()}
        onRowClick={(r) => navigate(`/planning/${r.id}`)}
        empty={{
          title:
            filter === "all"
              ? "No previous plans yet"
              : `No ${STAGES[filter as Stage].label.toLowerCase()} plans`,
          description: "Approved, completed and cancelled plans are kept here.",
        }}
      />
    </div>
  );
}
