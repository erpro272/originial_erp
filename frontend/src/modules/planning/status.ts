import type { Plan } from "./api";
import { generatedLabel } from "./format";

/** "Awaiting owner approval" / "Changes requested" / "Approved" / "Needs re-approval". */
/** Draft or awaiting approval: the only plans that can be edited. */
export function isWorking(plan: Pick<Plan, "status">): boolean {
  return plan.status === "draft" || plan.status === "generated";
}

export const STAGES = {
  draft: { label: "Draft", tone: "lo" },
  awaiting: { label: "Awaiting approval", tone: "md" },
  approved: { label: "Approved", tone: "ok" },
  needs_reapproval: { label: "Needs re-approval", tone: "hi" },
  completed: { label: "Completed", tone: "bl" },
  cancelled: { label: "Cancelled", tone: "lo" },
} as const;
export type Stage = keyof typeof STAGES;

export function planStatus(plan: Plan): { tone: "md" | "ok" | "hi" | "lo" | "bl"; text: string } {
  if (plan.status === "completed")
    return {
      tone: "bl",
      text: `Completed${plan.completed_at ? ` · ${generatedLabel(plan.completed_at)}` : ""}`,
    };
  if (plan.status === "cancelled") return { tone: "lo", text: "Cancelled" };
  if (plan.status === "approved")
    return plan.needs_reapproval
      ? { tone: "hi", text: `Rev ${plan.revision?.number ?? 2} · needs re-approval` }
      : {
          tone: "ok",
          text: `Approved${plan.approved_at ? ` · ${generatedLabel(plan.approved_at)}` : ""}`,
        };
  if (plan.regenerate) return { tone: "hi", text: "Orders changed · generate again" };
  if (plan.changes_requested) return { tone: "hi", text: "Changes requested" };
  return { tone: "md", text: "Awaiting owner approval" };
}

/** Plans the owner may delete: never approved (draft, awaiting approval, cancelled). */
export const DELETABLE_STATUSES = ["draft", "generated", "cancelled"];
