import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
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
import { plural, range } from "./format";
import { STAGES, type Stage } from "./status";

type Filter = "all" | Stage;
const ORDER: Stage[] = [
  "draft",
  "awaiting",
  "approved",
  "needs_reapproval",
  "completed",
  "cancelled",
];

/** Every plan, by stage. Opening one shows its 5 steps (approved ones exactly as approved). */
export function PlansDashboard() {
  const { can } = useAuth();
  const plans = usePlans();
  const create = useCreatePlan();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const rows = plans.data ?? [];
  const shown = filter === "all" ? rows : rows.filter((r) => r.stage === filter);
  const working = rows.find((r) => r.stage === "draft" || r.stage === "awaiting");

  const newPlan = async () => {
    if (working) {
      // one plan is worked on at a time: open it instead of starting a second
      toast({
        title: `${working.number} is still being worked on`,
        description: "Approve or cancel it to start the next one.",
      });
      navigate(`/planning/${working.id}`);
      return;
    }
    try {
      const p = await create.mutateAsync();
      navigate(`/planning/${p.id}`);
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
        return (
          <Tag tone={s.tone} size="sm">
            {s.label}
          </Tag>
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
  ];

  return (
    <div className="flex flex-col gap-7">
      <PageActions>
        {can("planning.write") && (
          <Button onClick={newPlan} disabled={create.isPending}>
            + New plan
          </Button>
        )}
      </PageActions>
      <PageHeader
        title="Manufacturing plans"
        subtitle="Every plan: what's being worked on, what's approved and what's done. Open one to see its orders, schedule, money and approval."
      />
      {working && (
        <button
          type="button"
          onClick={() => navigate(`/planning/${working.id}`)}
          className="flex cursor-pointer flex-wrap items-center justify-between gap-3 rounded-card border border-bl-line bg-surface-blue px-5 py-4 text-left text-sm"
        >
          <span>
            <b className="font-mono">{working.number}</b> is being worked on ·{" "}
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
      <DataTable<PlanSummary>
        tableId="planning-plans"
        title="Plans"
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
              ? "No plans yet"
              : `No ${STAGES[filter as Stage].label.toLowerCase()} plans`,
          description:
            "Send accepted orders to Planning from Orders received, or start a plan with + New plan.",
        }}
      />
    </div>
  );
}
