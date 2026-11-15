import type { Plan } from "./api";
import { generatedLabel } from "./format";

/** "Awaiting owner approval" / "Changes requested" / "Approved" / "Needs re-approval". */
export function planStatus(plan: Plan): { tone: "md" | "ok" | "hi" | "lo"; text: string } {
  if (plan.status === "approved")
    return plan.needs_reapproval
      ? { tone: "hi", text: "Needs re-approval" }
      : {
          tone: "ok",
          text: `Approved${plan.approved_at ? ` · ${generatedLabel(plan.approved_at)}` : ""}`,
        };
  if (plan.changes_requested) return { tone: "hi", text: "Changes requested" };
  return { tone: "md", text: "Awaiting owner approval" };
}
