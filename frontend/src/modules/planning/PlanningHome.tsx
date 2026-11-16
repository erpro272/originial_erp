import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useCreatePlan, useCurrentPlan, usePlans } from "./api";
import { PlanningPage } from "./PlanningPage";

/** `/planning`: the one active plan (draft or awaiting approval). With none, a quiet page to start the
 * next one; approved plans live in Plan history. */
export function PlanningHome() {
  const current = useCurrentPlan();
  if (current.isLoading) return <LoadingState label="Loading the plan" />;
  if (current.data) return <PlanningPage planId={current.data.id} />;
  return <NoActivePlan error={current.isError} />;
}

function NoActivePlan({ error }: { error: boolean }) {
  const { can } = useAuth();
  const plans = usePlans();
  const create = useCreatePlan();
  const navigate = useNavigate();
  const { toast } = useToast();
  const revisions = (plans.data ?? []).filter((p) => p.stage === "needs_reapproval");
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
      {revisions.map((r) => (
        <div
          key={r.id}
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-hi-line bg-hi-wash px-5 py-3 text-sm"
        >
          <span>
            <b className="font-mono">{r.number}</b>
            {r.revision ? ` · Rev ${r.revision}` : ""} needs re-approval
            {r.reapproval_reason ? `: ${r.reapproval_reason}` : ""}
          </span>
          <button
            type="button"
            onClick={() => navigate(`/planning/${r.id}?view=live`)}
            className="cursor-pointer border-0 bg-transparent p-0 text-[13px] text-link"
          >
            See what changed →
          </button>
        </div>
      ))}
      <EmptyState
        title={error ? "Couldn't load the plan" : "No active plan"}
        description="Approved plans are kept in Plan history. Send accepted orders to Planning from Orders received, or start the next plan here."
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
