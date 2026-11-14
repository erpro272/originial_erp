import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { StepTabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { useCreatePlan, usePlan } from "./api";
import { SelectedOrders } from "./SelectedOrders";

const STEPS = [
  { id: "1", label: "Selected orders" },
  { id: "2", label: "Proposed manufacturing sequence" },
  { id: "3", label: "Production schedule" },
  { id: "4", label: "Financial analysis" },
  { id: "5", label: "Final plan approval" },
];

/** Planning (rebuild): step 1 "Selected orders" is live; steps 2–5 are locked until they are built. */
export function PlanningPage() {
  const { can } = useAuth();
  const plan = usePlan();
  const create = useCreatePlan();
  const { toast } = useToast();
  const [params, setParams] = useSearchParams();
  const step = params.get("step") ?? "1";

  const start = async () => {
    try {
      await create.mutateAsync();
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't start a plan.", tone: "error" });
    }
  };
  const p = plan.data;

  return (
    <div className="flex flex-col gap-7">
      <PageHeader
        title="Order manufacturing plan"
        subtitle="Pick the accepted orders, set their priority, and check the plan is feasible before it goes to production."
      />
      {plan.isLoading ? (
        <LoadingState label="Loading the plan" />
      ) : !p ? (
        <EmptyState
          title="No orders in planning yet"
          description="Send accepted orders to Planning from Orders received, or start a plan from all accepted orders."
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
            active={step}
            onSelect={(id) => setParams(id === "1" ? {} : { step: id })}
            steps={STEPS.map((s) => ({ ...s, locked: s.id !== "1" }))}
          />
          {step !== "1" ? (
            <section className="flex flex-col items-center gap-3.5 rounded-card border border-dashed border-faint bg-surface px-6 py-16 text-center">
              <h2 className="m-0 text-xl font-semibold">
                {STEPS.find((s) => s.id === step)?.label} · coming soon
              </h2>
              <p className="m-0 text-sm text-muted">
                This step is being rebuilt. Selected orders is ready to use.
              </p>
              <Button variant="pill" onClick={() => setParams({})}>
                ← Selected orders
              </Button>
            </section>
          ) : (
            <SelectedOrders plan={p} />
          )}
        </>
      )}
    </div>
  );
}
