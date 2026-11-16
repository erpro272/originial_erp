import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/Skeleton";
import { StepTabs } from "@/components/ui/Tabs";
import { Modal } from "@/components/ui/Modal";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { useCancelPlan, useGenerate, usePlan, type Plan } from "./api";
import { RevisionPanel } from "./RevisionPanel";
import { DeletePlanDialog } from "./DeletePlan";
import { generatedLabel, plural } from "./format";
import { DELETABLE_STATUSES, isWorking, planStatus } from "./status";
import { SelectedOrders } from "./SelectedOrders";
import { ApprovalStep } from "./ApprovalStep";
import { FinanceStep } from "./FinanceStep";
import { ScheduleStep } from "./ScheduleStep";
import { SequenceStep } from "./SequenceStep";

const STEPS = [
  { id: "1", label: "Selected orders" },
  { id: "2", label: "Proposed manufacturing sequence" },
  { id: "3", label: "Production schedule" },
  { id: "4", label: "Financial analysis" },
  { id: "5", label: "Final plan approval" },
];
const BUILT = ["1", "2", "3", "4", "5"];

/** One plan, in 5 steps. The active plan opens at `/planning` (PlanningHome); history plans at
 * `/planning/:planId?step=1..5`. Draft and awaiting plans can be edited; approved ones open on their frozen
 * approved version (`view=live` shows the recalculation); completed and cancelled plans are history. */
export function PlanningPage({ planId: active }: { planId?: string } = {}) {
  const { planId: routeId } = useParams();
  const planId = active ?? routeId;
  const [params, setParams] = useSearchParams();
  const step = params.get("step") ?? "1";
  const view = params.get("view") === "live" ? "live" : undefined;
  const plan = usePlan(planId, view);
  const go = (id: string) => {
    const next: Record<string, string> = id === "1" ? {} : { step: id };
    if (view) next.view = view;
    setParams(next);
    window.scrollTo({ top: 0 });
  };
  const setView = (v: "live" | undefined) => {
    const next: Record<string, string> = step === "1" ? {} : { step };
    if (v) next.view = v;
    setParams(next);
  };
  const p = plan.data;
  const generated = !!p?.generated_at;
  const open = (id: string) => id === "1" || (generated && BUILT.includes(id));

  // "Plan updated · N tabs changed": a dot on each changed step until it is opened.
  const [seen, setSeen] = useState<Record<string, number>>({});
  const version = p?.version ?? 0;
  if (p && seen[step] !== version) setSeen({ ...seen, [step]: version }); // opened: no dot any more
  const changed = new Set((p?.last_change?.tabs ?? []).map(String));
  const status = p ? planStatus(p) : null;

  return (
    <div className="flex flex-col gap-7">
      <div className="flex flex-col gap-3">
        <span className="flex justify-between gap-4 text-[13px]">
          {p && isWorking(p) ? (
            <span />
          ) : (
            <Link to="/planning/history" className="no-underline">
              ← Plan history
            </Link>
          )}
          {p && isWorking(p) && (
            <Link to="/planning/history" className="no-underline">
              Plan history →
            </Link>
          )}
        </span>
        <PageHeader
          title={
            <span className="flex flex-wrap items-center gap-3">
              Order manufacturing plan
              {p && (
                <span className="font-mono text-[22px] font-semibold text-muted">{p.number}</span>
              )}
              {status && <Tag tone={status.tone}>{status.text}</Tag>}
            </span>
          }
          subtitle="Pick the accepted orders, set their priority, and check the plan is feasible before it goes to production."
        />
      </div>
      {plan.isLoading ? (
        <LoadingState label="Loading the plan" />
      ) : plan.isError || !p ? (
        <EmptyState
          title="Plan not found"
          description="It may belong to another company, or the link is wrong."
          actions={
            <Link to="/planning/history">
              <Button variant="pill">Plan history</Button>
            </Link>
          }
        />
      ) : (
        <>
          <PlanBanner plan={p} view={view} onView={setView} go={go} />
          {p.status === "approved" && <RevisionPanel plan={p} />}
          <StepTabs
            label="Plan steps"
            active={step}
            onSelect={go}
            steps={STEPS.map((s) => ({
              ...s,
              locked: !open(s.id),
              changed:
                isWorking(p) &&
                open(s.id) &&
                s.id !== step &&
                changed.has(s.id) &&
                (seen[s.id] ?? -1) < version,
            }))}
          />
          {step === "1" ? (
            <SelectedOrders plan={p} go={go} />
          ) : step === "2" && generated ? (
            <SequenceStep plan={p} go={go} />
          ) : step === "3" && generated ? (
            <ScheduleStep plan={p} go={go} />
          ) : step === "4" && generated ? (
            <FinanceStep plan={p} go={go} />
          ) : step === "5" && generated ? (
            <ApprovalStep plan={p} go={go} />
          ) : (
            <LockedStep plan={p} step={step} go={go} />
          )}
        </>
      )}
    </div>
  );
}

/** What kind of plan this is, when it isn't an editable one: approved snapshot / recalculation /
 * completed / cancelled; plus Cancel for an owner on a working plan. */
function PlanBanner({
  plan: p,
  view,
  onView,
  go,
}: {
  plan: Plan;
  view: "live" | undefined;
  onView: (v: "live" | undefined) => void;
  go: (id: string) => void;
}) {
  const { can } = useAuth();
  const [cancelling, setCancelling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const navigate = useNavigate();
  const link = "cursor-pointer border-0 bg-transparent p-0 text-[13px] text-link";
  const owner = can("planning.approve");
  const deleteLink = owner && DELETABLE_STATUSES.includes(p.status) && (
    <>
      <button type="button" className={cn(link, "text-hi")} onClick={() => setDeleting(true)}>
        Delete this plan
      </button>
      {deleting && (
        <DeletePlanDialog
          plan={p}
          onClose={() => setDeleting(false)}
          onDeleted={() => navigate("/planning")}
        />
      )}
    </>
  );
  if (isWorking(p)) {
    return (
      <>
        {p.regenerate && <RegenerateBanner plan={p} />}
        {owner && (
          <div className="-mt-3 flex justify-end gap-5">
            <button type="button" className={link} onClick={() => setCancelling(true)}>
              Cancel this plan
            </button>
            {deleteLink}
            {cancelling && <CancelDialog plan={p} onClose={() => setCancelling(false)} />}
          </div>
        )}
      </>
    );
  }
  const box =
    "flex flex-wrap items-center justify-between gap-3 rounded-card border px-5 py-3 text-sm";
  if (p.status === "cancelled")
    return (
      <div role="status" className={cn(box, "border-line bg-surface")}>
        <span>
          <b>Cancelled{p.cancelled_at ? ` ${generatedLabel(p.cancelled_at)}` : ""}</b>
          {p.cancel_reason ? ` · “${p.cancel_reason}”` : ""}. Kept as history, read-only; its orders
          went back to Orders received.
        </span>
        {deleteLink}
      </div>
    );
  if (p.status === "completed")
    return (
      <div role="status" className={cn(box, "border-bl-line bg-surface-blue")}>
        <span>
          <b>Completed{p.completed_at ? ` ${generatedLabel(p.completed_at)}` : ""}</b>: every order
          in it has shipped. Showing the approved version (v{p.snapshot?.version ?? 1}), read-only.
        </span>
      </div>
    );
  // approved
  if (view === "live")
    return (
      <div role="status" className={cn(box, "border-hi-line bg-hi-wash")}>
        <span>
          <b>Recalculated with today's orders, stock and factory data</b>, not what was approved
          {p.needs_reapproval ? ". It differs from the approved version." : "."}
        </span>
        <span className="flex gap-4">
          <button type="button" className={link} onClick={() => onView(undefined)}>
            ← Approved version
          </button>
          {p.needs_reapproval && can("planning.approve") && (
            <button type="button" className={link} onClick={() => go("5")}>
              Re-approve →
            </button>
          )}
        </span>
      </div>
    );
  return (
    <div
      role="status"
      className={cn(
        box,
        p.needs_reapproval ? "border-hi-line bg-hi-wash" : "border-ok-line bg-ok-bg",
      )}
    >
      <span>
        <b>
          Approved version v{p.snapshot?.version ?? 1}
          {p.snapshot ? `, ${generatedLabel(p.snapshot.approved_at)}` : ""}
        </b>
        , exactly as approved and read-only.
        {p.needs_reapproval
          ? ` Rev ${p.revision?.number ?? 2} needs re-approval: see what changed below.`
          : ""}
      </span>
      <button type="button" className={link} onClick={() => onView("live")}>
        {p.needs_reapproval ? "See what changed →" : "Recalculate with today's data →"}
      </button>
    </div>
  );
}

/** Orders were added or removed after Generate plan: generate again before it can be approved. */
function RegenerateBanner({ plan }: { plan: Plan }) {
  const { can } = useAuth();
  const generate = useGenerate(plan.id);
  const { toast } = useToast();
  const r = plan.regenerate!;
  const parts = [
    r.added.length ? `${r.added.join(", ")} added` : "",
    r.removed.length ? `${r.removed.join(", ")} removed` : "",
  ].filter(Boolean);
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-hi-line bg-hi-wash px-5 py-3 text-sm"
    >
      <span>
        <b>Orders changed since the plan was generated</b> ({parts.join("; ")}). It is back to
        draft: generate it again before approval.
      </span>
      {can("planning.write") && (
        <Button
          disabled={generate.isPending}
          onClick={async () => {
            try {
              await generate.mutateAsync();
              toast({ title: "Plan generated again", tone: "success" });
            } catch (e) {
              toast({
                title: e instanceof ApiError ? e.message : "Couldn't generate.",
                tone: "error",
              });
            }
          }}
        >
          Generate again
        </Button>
      )}
    </div>
  );
}

function CancelDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const cancel = useCancelPlan(plan.id);
  const { toast } = useToast();
  const navigate = useNavigate();
  const [reason, setReason] = useState("");
  return (
    <Modal
      open
      tone="danger"
      onOpenChange={(o) => !o && onClose()}
      title={`Cancel ${plan.number}?`}
      description="It stays in the plans list as Cancelled. Its orders go back to Orders received (accepted, not in planning)."
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Keep the plan
          </Button>
          <Button
            disabled={!reason.trim() || cancel.isPending}
            onClick={async () => {
              try {
                await cancel.mutateAsync(reason.trim());
                toast({ title: `${plan.number} cancelled`, tone: "success" });
                onClose();
                navigate("/planning");
              } catch (e) {
                toast({
                  title: e instanceof ApiError ? e.message : "Couldn't cancel the plan.",
                  tone: "error",
                });
              }
            }}
          >
            Cancel plan
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Reason
        <textarea
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Customer moved the delivery dates"
          className="rounded-xl border border-line-input px-3.5 py-2.5 text-sm font-normal"
        />
      </label>
    </Modal>
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
          ? "This step is being rebuilt. Steps 1–4 are ready to use."
          : `Generate a plan from your ${plural(n, "selected order")} to see this step.`}
      </p>
      <div className="flex gap-2.5">
        <Button variant="pill" onClick={() => go(generated ? "4" : "1")}>
          {generated ? "← Financial analysis" : "Review selected orders"}
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
