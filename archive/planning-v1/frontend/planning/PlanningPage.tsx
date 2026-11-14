import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { PageActions } from "@/components/layout/PageActions";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { StepTabs } from "@/components/ui/Tabs";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { ApiError } from "@/api/client";
import { useCreatePlan, useGenerate, usePlan, type Plan } from "./api";
import { plural } from "./format";
import { ApprovalTab } from "./tabs/ApprovalTab";
import { FinanceTab } from "./tabs/FinanceTab";
import { ScheduleTab } from "./tabs/ScheduleTab";
import { SelectedOrdersTab } from "./tabs/SelectedOrdersTab";
import { SequenceTab } from "./tabs/SequenceTab";

const STEPS = [
  { id: "1", label: "Selected orders" },
  { id: "2", label: "Proposed manufacturing sequence" },
  { id: "3", label: "Production schedule" },
  { id: "4", label: "Financial analysis" },
  { id: "5", label: "Final plan approval" },
];

export interface TabProps {
  plan: Plan;
  go: (step: number) => void;
}

/** Planning: one plan, five connected steps. Every number comes from the server's recalculation. */
export function PlanningPage() {
  const { can } = useAuth();
  const plan = usePlan();
  const create = useCreatePlan();
  const { toast } = useToast();
  const [params, setParams] = useSearchParams();
  const step = Number(params.get("step") ?? "1");
  // Tabs whose numbers changed since the owner last looked at them.
  const [unseen, setUnseen] = useState<Set<number>>(new Set());
  const [banner, setBanner] = useState<{ summary: string; tabs: number[] } | null>(null);
  const [seenVersion, setSeenVersion] = useState<number | null>(null);
  const p = plan.data;
  if (p && p.version !== seenVersion) {
    // A new version arrived (any edit, here or in another module): mark the tabs it changed.
    setSeenVersion(p.version);
    if (seenVersion !== null && p.last_change?.tabs.length) {
      setUnseen(new Set([...unseen, ...p.last_change.tabs.filter((t) => t !== step)]));
      setBanner({ summary: p.last_change.summary, tabs: p.last_change.tabs });
    }
  }
  const go = (n: number) => {
    setParams(n === 1 ? {} : { step: String(n) });
    setUnseen((s) => new Set([...s].filter((t) => t !== n)));
    window.scrollTo({ top: 0 });
  };

  const start = async () => {
    try {
      await create.mutateAsync();
      go(1);
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't start a plan.", tone: "error" });
    }
  };
  const working = p && (p.status === "draft" || p.status === "generated");

  return (
    <div className="flex flex-col gap-7">
      {can("planning.write") && (
        <PageActions>
          <Button onClick={start} disabled={!!working || create.isPending}>
            + New plan
          </Button>
        </PageActions>
      )}
      <PageHeader
        title="Order manufacturing plan"
        subtitle="Pick the accepted orders, set their priority, and check the plan is feasible before it goes to production."
        aside={
          <div className="flex flex-wrap items-center gap-2">
            {p && (
              <span className="flex items-center gap-2 text-sm text-muted">
                <span className="font-mono text-ink-2">{p.number}</span>
                <StatusTag plan={p} />
              </span>
            )}
            <Button asChild variant="pill" size="pill">
              <Link to="/planning/factory">Factory setup</Link>
            </Button>
          </div>
        }
      />

      {plan.isLoading ? (
        <LoadingState label="Loading the plan" />
      ) : !p ? (
        <EmptyState
          title="No plan yet"
          description="Start a plan from the accepted orders you sent to Planning from Orders received."
          actions={
            can("planning.write") ? (
              <Button onClick={start} disabled={create.isPending}>
                Start a plan
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <StepTabs
            label="Plan steps"
            active={String(step)}
            onSelect={(id) => go(Number(id))}
            steps={STEPS.map((s) => ({
              ...s,
              locked: p.status === "draft" && s.id !== "1",
              changed: unseen.has(Number(s.id)),
            }))}
          />
          {banner && (
            <div
              role="status"
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-bl-line bg-surface-blue px-4 py-2.5 text-sm"
            >
              <span>
                <b>Plan updated</b>
                {banner.tabs.length > 0 && ` · ${plural(banner.tabs.length, "tab")} changed`}
                <span className="text-muted"> · {banner.summary}</span>
              </span>
              <button
                type="button"
                className="cursor-pointer border-0 bg-transparent text-[13px] text-link"
                onClick={() => setBanner(null)}
              >
                Dismiss
              </button>
            </div>
          )}
          {p.needs_reapproval && (
            <div className="rounded-xl border border-md-line bg-md-bg px-4 py-2.5 text-sm text-md">
              <b>Needs re-approval.</b> Something changed after this plan was approved. Check the
              steps and approve it again in step 5.
            </div>
          )}
          {p.status === "draft" && step !== 1 ? (
            <LockedStep plan={p} step={step} go={go} />
          ) : step === 2 ? (
            <SequenceTab plan={p} go={go} />
          ) : step === 3 ? (
            <ScheduleTab plan={p} go={go} />
          ) : step === 4 ? (
            <FinanceTab plan={p} go={go} />
          ) : step === 5 ? (
            <ApprovalTab plan={p} go={go} />
          ) : (
            <SelectedOrdersTab plan={p} go={go} />
          )}
        </>
      )}
    </div>
  );
}

function StatusTag({ plan }: { plan: Plan }) {
  if (plan.needs_reapproval) return <Tag tone="md">Needs re-approval</Tag>;
  if (plan.status === "approved") return <Tag tone="ok">Approved</Tag>;
  if (plan.status === "generated") return <Tag tone="md">Awaiting owner approval</Tag>;
  return <Tag tone="lo">Draft</Tag>;
}

function LockedStep({ plan, step, go }: { plan: Plan; step: number; go: (n: number) => void }) {
  const gen = useGenerate(plan.id);
  const { can } = useAuth();
  const n = plan.result.sequence.rows.length;
  return (
    <section className="flex flex-col items-center gap-3.5 rounded-card border border-dashed border-faint bg-surface px-6 py-16 text-center">
      <h2 className="m-0 text-xl font-semibold">
        {STEPS[step - 1]?.label} · no plan generated yet
      </h2>
      <p className="m-0 text-sm text-muted">
        Generate a plan from your {plural(n, "selected order")} to see this step.
      </p>
      <div className="flex gap-2">
        <Button variant="pill" onClick={() => go(1)}>
          Review selected orders
        </Button>
        {can("planning.write") && (
          <Button
            onClick={async () => {
              await gen.mutateAsync();
              go(step);
            }}
            disabled={n === 0 || gen.isPending}
          >
            Generate plan →
          </Button>
        )}
      </div>
    </section>
  );
}
