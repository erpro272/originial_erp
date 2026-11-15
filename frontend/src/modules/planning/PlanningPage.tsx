import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { StepTabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { useCreatePlan, useGenerate, usePlan, type Plan } from "./api";
import { plural } from "./format";
import { SelectedOrders } from "./SelectedOrders";
import { ScheduleStep } from "./ScheduleStep";
import { SequenceStep } from "./SequenceStep";

const STEPS = [
  { id: "1", label: "Selected orders" },
  { id: "2", label: "Proposed manufacturing sequence" },
  { id: "3", label: "Production schedule" },
  { id: "4", label: "Financial analysis" },
  { id: "5", label: "Final plan approval" },
];
const BUILT = ["1", "2", "3"]; // steps 4–5 are being rebuilt

/** Planning (rebuild): steps 1–3 are live; 2–3 open once the plan is generated; 4–5 come next. */
export function PlanningPage() {
  const { can } = useAuth();
  const plan = usePlan();
  const create = useCreatePlan();
  const { toast } = useToast();
  const [params, setParams] = useSearchParams();
  const step = params.get("step") ?? "1";
  const go = (id: string) => {
    setParams(id === "1" ? {} : { step: id });
    window.scrollTo({ top: 0 });
  };

  const start = async () => {
    try {
      await create.mutateAsync();
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : "Couldn't start a plan.", tone: "error" });
    }
  };
  const p = plan.data;
  const generated = !!p?.generated_at;
  const open = (id: string) => id === "1" || (generated && BUILT.includes(id));

  // "Plan updated · N tabs changed": a dot on each changed step until it is opened.
  const [seen, setSeen] = useState<Record<string, number>>({});
  const version = p?.version ?? 0;
  if (p && seen[step] !== version) setSeen({ ...seen, [step]: version }); // opened: no dot any more
  const changed = new Set((p?.last_change?.tabs ?? []).map(String));

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
            onSelect={go}
            steps={STEPS.map((s) => ({
              ...s,
              locked: !open(s.id),
              changed:
                open(s.id) && s.id !== step && changed.has(s.id) && (seen[s.id] ?? -1) < version,
            }))}
          />
          {step === "1" ? (
            <SelectedOrders plan={p} go={go} />
          ) : step === "2" && generated ? (
            <SequenceStep plan={p} go={go} />
          ) : step === "3" && generated ? (
            <ScheduleStep plan={p} go={go} />
          ) : (
            <LockedStep plan={p} step={step} go={go} />
          )}
        </>
      )}
    </div>
  );
}

function LockedStep({ plan, step, go }: { plan: Plan; step: string; go: (id: string) => void }) {
  const { can } = useAuth();
  const generate = useGenerate(plan.id);
  const { toast } = useToast();
  const label = STEPS.find((s) => s.id === step)?.label ?? "This step";
  const n = plan.result.selection.selected.length;
  const generated = !!plan.generated_at;
  return (
    <section className="flex flex-col items-center gap-3.5 rounded-card border border-dashed border-faint bg-surface px-6 py-16 text-center">
      <span
        aria-hidden
        className="grid size-11 place-items-center rounded-full bg-surface-blue text-primary"
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M3 3v18h18" />
          <path d="M7 15l4-4 3 3 5-6" />
        </svg>
      </span>
      <h2 className="m-0 text-xl font-semibold">
        {label} · {generated ? "coming next" : "no plan generated yet"}
      </h2>
      <p className="m-0 max-w-[460px] text-[15px] text-muted">
        {generated
          ? "This step is being rebuilt. Selected orders, the proposed sequence and the production schedule are ready to use."
          : `Generate a plan from your ${plural(n, "selected order")} to see this step.`}
      </p>
      <div className="flex gap-2.5">
        <Button variant="pill" onClick={() => go(generated ? "3" : "1")}>
          {generated ? "← Production schedule" : "Review selected orders"}
        </Button>
        {!generated && can("planning.write") && (
          <Button
            disabled={!n || generate.isPending}
            onClick={async () => {
              try {
                await generate.mutateAsync();
                go("2");
              } catch (e) {
                toast({
                  title: e instanceof ApiError ? e.message : "Couldn't generate the plan.",
                  tone: "error",
                });
              }
            }}
          >
            Generate plan →
          </Button>
        )}
      </div>
    </section>
  );
}
