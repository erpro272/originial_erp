import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type Plan = Schemas["PlanOut"];
export type Selection = Schemas["Selection"];
export type SelectionOption = Schemas["SelectionOption"];
export type PlanPatch = Schemas["PlanPatch"];
export type SeqRow = Schemas["SeqRow"];
export type Sequence = Schemas["Sequence"];
export type GanttRow = Schemas["GanttRow"];
export type Preview = Schemas["PreviewOut"];
export type Rules = Schemas["PlanningRules"];
export type Finance = Schemas["Finance"];
export type OptKey = "own" | "part" | "full";

export const PLAN_KEY = ["planning", "plan"] as const;
export type PlanSummary = Schemas["PlanSummary"];
export type PlanView = "live" | "snapshot";

/** The working plan (or the latest approved one). Starts a draft when orders were sent to Planning. */
export function useCurrentPlan() {
  return useQuery({
    queryKey: [...PLAN_KEY, "current"],
    queryFn: async () => unwrap(await api.GET("/api/planning/plan")),
  });
}

/** One plan. Approved / completed plans open on their frozen approved version unless view = "live". */
export function usePlan(planId: string | undefined, view?: PlanView) {
  return useQuery({
    queryKey: [...PLAN_KEY, planId, view ?? "default"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/planning/plans/{plan_id}", {
          params: { path: { plan_id: planId! }, query: view ? { view } : {} },
        }),
      ),
    enabled: !!planId,
  });
}

/** Every plan for the dashboard (asks for the current plan first, so orders sent to Planning get a draft). */
export function usePlans() {
  return useQuery({
    queryKey: ["planning", "plans"],
    queryFn: async () => {
      unwrap(await api.GET("/api/planning/plan"));
      return unwrap(await api.GET("/api/planning/plans"));
    },
  });
}

function useSetPlan() {
  const qc = useQueryClient();
  return (p: Plan) => {
    if (p.status === "draft" || p.status === "generated") {
      qc.setQueryData([...PLAN_KEY, p.id, "default"], p); // working plans: the response is the live plan
    } else {
      void qc.invalidateQueries({ queryKey: [...PLAN_KEY, p.id] }); // approved: reload snapshot + live views
    }
    void qc.invalidateQueries({ queryKey: ["planning", "plans"] });
    void qc.invalidateQueries({ queryKey: [...PLAN_KEY, "current"] });
    void qc.invalidateQueries({ queryKey: ["orders"] }); // ticks are "In planning" in Orders received
  };
}

/** Owner: cancel a draft / awaiting plan (its orders go back to accepted, not in planning). */
export function useCancelPlan(planId: string | undefined) {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async (reason: string) =>
      unwrap(
        await api.POST("/api/planning/plans/{plan_id}/cancel", {
          params: { path: { plan_id: planId! } },
          body: { reason },
        }),
      ),
    onSuccess: set,
  });
}

export function useCreatePlan() {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/planning/plans")),
    onSuccess: set,
  });
}

/** Tick/untick orders or use an option. The response carries the recalculated plan. */
export function usePatchPlan(planId: string | undefined) {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async (body: PlanPatch) =>
      unwrap(
        await api.PATCH("/api/planning/plans/{plan_id}", {
          params: { path: { plan_id: planId! } },
          body,
        }),
      ),
    onSuccess: (r) => set(r.plan),
  });
}

/** Generate (or recalculate) the plan: opens step 2 and stamps "Generated today, HH:MM". */
export function useGenerate(planId: string | undefined) {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/planning/plans/{plan_id}/generate", {
          params: { path: { plan_id: planId! } },
        }),
      ),
    onSuccess: set,
  });
}

export const OPT_LABEL: Record<OptKey, string> = {
  own: "Your selection",
  part: "Partly optimized",
  full: "Fully optimized",
};

/** Simulate an edit without saving it (the reorder / finish-date warning). */
export async function previewPatch(planId: string, body: PlanPatch): Promise<Preview> {
  return unwrap(
    await api.PATCH("/api/planning/plans/{plan_id}", {
      params: { path: { plan_id: planId }, query: { preview: true } },
      body,
    }),
  );
}

/** Step 3 "Save schedule": a checkpoint in the plan history. */
export function useSaveSchedule(planId: string | undefined) {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/planning/plans/{plan_id}/save-schedule", {
          params: { path: { plan_id: planId! } },
        }),
      ),
    onSuccess: set,
  });
}

/** Machine colours on the schedule, by machine order in Factory setup. */
const PALETTE = [
  "bg-ai-bg border-ai-line text-ai", // purple (mockup: Press 01)
  "bg-bl-bg border-bl-line text-bl", // blue (CNC 01)
  "bg-te-bg border-te-line text-te", // teal
  "bg-in-bg border-in-line text-in", // indigo
  "bg-surface-2 border-faint text-ink-3", // grey
];
export function machineTone(machineId: string, order: string[]): string {
  const i = order.indexOf(machineId);
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length]!;
}

/** Company rules (late penalty, overheads, packaging, minimum margin): the comment-icon numbers. */
export function useRules() {
  return useQuery({
    queryKey: ["planning", "rules"],
    queryFn: async () => unwrap(await api.GET("/api/planning/rules")),
  });
}

export function usePutRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Rules) => unwrap(await api.PUT("/api/planning/rules", { body })),
    onSuccess: (r) => {
      qc.setQueryData(["planning", "rules"], r);
      void qc.invalidateQueries({ queryKey: PLAN_KEY }); // the plan recalculates with the new rule
    },
  });
}

export type HistoryItem = Schemas["HistoryItem"];

/** The plan's history (newest first): every change, generate, save, send back, approval. */
export function useHistory(planId: string | undefined, version: number | undefined) {
  return useQuery({
    queryKey: ["planning", "history", planId, version],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/planning/plans/{plan_id}/history", {
          params: { path: { plan_id: planId! } },
        }),
      ),
    enabled: !!planId,
  });
}

function usePlanAction<B>(call: (body: B) => Promise<Plan>) {
  const set = useSetPlan();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (p) => {
      set(p);
      void qc.invalidateQueries({ queryKey: ["planning", "history"] });
    },
  });
}

/** Owner: approve (POs to Purchasing, promised dates to Orders). */
export function useApprove(planId: string | undefined) {
  return usePlanAction(async (body: Schemas["ApproveIn"]) =>
    unwrap(
      await api.POST("/api/planning/plans/{plan_id}/approve", {
        params: { path: { plan_id: planId! } },
        body,
      }),
    ),
  );
}

/** Owner: send back to edit, with a note. */
export function useSendBack(planId: string | undefined) {
  return usePlanAction(async (body: Schemas["SendBackIn"]) =>
    unwrap(
      await api.POST("/api/planning/plans/{plan_id}/send-back", {
        params: { path: { plan_id: planId! } },
        body,
      }),
    ),
  );
}

/** Raise one material PO now (before approval). */
export function useRaisePo(planId: string | undefined) {
  return usePlanAction(async (material_id: string) =>
    unwrap(
      await api.POST("/api/planning/plans/{plan_id}/purchase-requests", {
        params: { path: { plan_id: planId! } },
        body: { material_id },
      }),
    ),
  );
}

/** Owner: delete a draft, awaiting or cancelled plan (approved / completed plans are kept for good). */
export function useDeletePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (planId: string) => {
      const r = await api.DELETE("/api/planning/plans/{plan_id}", {
        params: { path: { plan_id: planId } },
      });
      if (!r.response.ok) unwrap(r); // 204 = deleted; anything else carries the API error (throws)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["planning"] });
      void qc.invalidateQueries({ queryKey: ["orders"] }); // a deleted draft's orders leave planning
    },
  });
}
