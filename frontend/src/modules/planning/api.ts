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

/** The working plan. The server recalculates it whenever orders, stock or factory data changed. */
export function usePlan() {
  return useQuery({
    queryKey: PLAN_KEY,
    queryFn: async () => unwrap(await api.GET("/api/planning/plan")),
  });
}

function useSetPlan() {
  const qc = useQueryClient();
  return (p: Plan) => {
    qc.setQueryData(PLAN_KEY, p);
    void qc.invalidateQueries({ queryKey: ["orders"] }); // ticks are "In planning" in Orders received
  };
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
