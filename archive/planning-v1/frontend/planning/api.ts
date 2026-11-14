import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type Plan = Schemas["PlanOut"];
export type PlanResult = Schemas["PlanResult"];
export type PlanPatch = Schemas["PlanPatch"];
export type Preview = Schemas["PreviewOut"];
export type Bottleneck = Schemas["Bottleneck"];
export type Rules = Schemas["PlanningRules"];
export type Factory = Schemas["Factory-Output"];
export type SeqRow = Schemas["SeqRow"];
export type GanttRow = Schemas["GanttRow"];
export type SelectionOption = Schemas["SelectionOption"];

export const PLAN_KEY = ["planning", "plan"] as const;

/** The one plan every tab reads. The server recalculates it whenever anything it depends on changed. */
export function usePlan() {
  return useQuery({
    queryKey: PLAN_KEY,
    queryFn: async () => unwrap(await api.GET("/api/planning/plan")),
    refetchOnWindowFocus: true,
  });
}

function useSetPlan() {
  const qc = useQueryClient();
  return (p: Plan) => {
    qc.setQueryData(PLAN_KEY, p);
    void qc.invalidateQueries({ queryKey: ["planning", "history"] });
    // Approval and purchase requests change Orders too.
    void qc.invalidateQueries({ queryKey: ["orders"] });
  };
}

export function useCreatePlan() {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/planning/plans")),
    onSuccess: set,
  });
}

/** Any edit. The response carries the recalculated plan and which tabs changed. */
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

/** "What if": recalculates without saving (reorder warning). */
export async function previewPatch(planId: string, body: PlanPatch): Promise<Preview> {
  return unwrap(
    await api.PATCH("/api/planning/plans/{plan_id}", {
      params: { path: { plan_id: planId }, query: { preview: true } },
      body,
    }),
  );
}

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

export function useRaisePo(planId: string | undefined) {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async (materialId: string) =>
      unwrap(
        await api.POST("/api/planning/plans/{plan_id}/purchase-requests", {
          params: { path: { plan_id: planId! } },
          body: { material_id: materialId },
        }),
      ),
    onSuccess: set,
  });
}

export function useApprove(planId: string | undefined) {
  const set = useSetPlan();
  return useMutation({
    mutationFn: async (body: Schemas["ApproveIn"]) =>
      unwrap(
        await api.POST("/api/planning/plans/{plan_id}/approve", {
          params: { path: { plan_id: planId! } },
          body,
        }),
      ),
    onSuccess: set,
  });
}

export function useHistory(planId: string | undefined, version: number | undefined) {
  return useQuery({
    queryKey: ["planning", "history", planId, version],
    enabled: !!planId,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/planning/plans/{plan_id}/history", {
          params: { path: { plan_id: planId! } },
        }),
      ),
  });
}

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

export function useFactory() {
  return useQuery({
    queryKey: ["planning", "factory"],
    queryFn: async () => unwrap(await api.GET("/api/planning/factory")),
  });
}

export function usePutFactory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["Factory-Input"]) =>
      unwrap(await api.PUT("/api/planning/factory", { body })),
    onSuccess: (r) => {
      qc.setQueryData(["planning", "factory"], r);
      void qc.invalidateQueries({ queryKey: PLAN_KEY });
    },
  });
}

/** Machine colours on the schedule, by machine order in Factory setup. */
const PALETTE = [
  "bg-in-bg border-in-line text-in",
  "bg-bl-bg border-bl-line text-bl",
  "bg-te-bg border-te-line text-te",
  "bg-ai-bg border-ai-line text-ai",
  "bg-surface-2 border-faint text-ink-3",
];
export function machineTone(machineId: string, order: string[]): string {
  const i = order.indexOf(machineId);
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length]!;
}
