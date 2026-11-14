import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type Plan = Schemas["PlanOut"];
export type Selection = Schemas["Selection"];
export type SelectionOption = Schemas["SelectionOption"];
export type PlanPatch = Schemas["PlanPatch"];
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

export const OPT_LABEL: Record<OptKey, string> = {
  own: "Your selection",
  part: "Partly optimized",
  full: "Fully optimized",
};
