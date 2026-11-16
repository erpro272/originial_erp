import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { PageActions } from "@/components/layout/PageActions";
import { shortDate } from "@/lib/format";
import { useCreatePlan, useCurrentPlan, usePlans, type PlanSummary } from "./api";
import { PlanningPage } from "./PlanningPage";
import { plansInForce } from "./status";

/** `/planning`: the one active plan (draft or awaiting approval). With none, the approved plan in force,
 * read-only. With neither, a quiet page to start the next plan. */
export function PlanningHome() {
  const current = useCurrentPlan();
  const plans = usePlans();
  if (current.isLoading || plans.isLoading) return <LoadingState label="Loading the plan" />;
  const inForce = plansInForce(plans.data ?? []);
  if (current.data)
    return (
      <PlanningPage
        planId={current.data.id}
        home={inForce.length > 0 ? <InForceLine plans={inForce} /> : undefined}
      />
    );
  if (inForce.length > 0)
    return (
      <PlanningPage
        planId={inForce[0]!.id}
        home={<InForceBanner plan={inForce[0]!} others={inForce.slice(1)} />}
      />
    );
  return <NoActivePlan error={current.isError} />;
}

const link = "text-[13px] text-link no-underline";

/** Above the active plan: the approved plans still being made. */
export function InForceLine({ plans }: { plans: PlanSummary[] }) {
  return (
    <p className="m-0 -mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted">
      In force:
      {plans.map((p) => (
        <Link key={p.id} to={`/planning/${p.id}`} className={link}>
          {p.number} (approved {p.approved_at ? shortDate(p.approved_at) : ""}
          {p.stage === "needs_reapproval" ? ", needs re-approval" : ""}) →
        </Link>
      ))}
    </p>
  );
}

/** No plan being worked on: the approved plan in force is shown read-only; the next cycle starts with
 * "+ New plan" (top bar) or by sending orders to Planning. */
export function InForceBanner({ plan, others }: { plan: PlanSummary; others: PlanSummary[] }) {
  const { can } = useAuth();
  const create = useCreatePlan();
  const { toast } = useToast();
  const start = async () => {
    try {
      await create.mutateAsync();
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't start a plan.", tone: "error" });
    }
  };
  return (
    <>
      <PageActions>
        {can("planning.write") && (
          <Button onClick={start} disabled={create.isPending}>
            + New plan
          </Button>
        )}
      </PageActions>
      <p
        role="status"
        aria-label="Plan in force"
        className="m-0 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted"
      >
        <span>
          No plan is being worked on: showing <b className="font-mono text-ink">{plan.number}</b>,
          the plan in force, read-only. Start the next one with + New plan or by sending orders to
          Planning.
        </span>
        {others.length > 0 && (
          <span className="flex flex-wrap gap-4">
            Also in force:
            {others.map((p) => (
              <Link key={p.id} to={`/planning/${p.id}`} className={link}>
                {p.number}
                {p.stage === "needs_reapproval" ? " (needs re-approval)" : ""} →
              </Link>
            ))}
          </span>
        )}
      </p>
    </>
  );
}

function NoActivePlan({ error }: { error: boolean }) {
  const { can } = useAuth();
  const create = useCreatePlan();
  const { toast } = useToast();
  const start = async () => {
    try {
      await create.mutateAsync();
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't start a plan.", tone: "error" });
    }
  };
  return (
    <div className="flex flex-col gap-7">
      <PageHeader
        title="Order manufacturing plan"
        subtitle="Pick the accepted orders, set their priority, and check the plan is feasible before it goes to production."
      />
      <EmptyState
        title={error ? "Couldn't load the plan" : "No active plan"}
        description="No plan is being worked on and none is in force. Send accepted orders to Planning from Orders received, or start the next plan here."
        actions={
          <>
            {can("planning.write") && (
              <Button onClick={start} disabled={create.isPending}>
                + New plan
              </Button>
            )}
            <Link to="/planning/history">
              <Button variant="pill">Plan history</Button>
            </Link>
          </>
        }
      />
    </div>
  );
}
