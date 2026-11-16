import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type Inventory = Schemas["InventoryOut"];
export type MaterialRow = Schemas["MaterialRow"];
export type Po = Schemas["PoOut"];
export type RaisePo = Schemas["PoRaiseIn"];
export type PoDetail = Schemas["PoDetail"];
export type Purchases = Schemas["PurchasesOut"];

const KEY = ["purchasing"] as const;

/** Stock, reserved, on order and status per material; needs-attention cards; open POs. */
export function useInventory() {
  return useQuery({
    queryKey: [...KEY, "inventory"],
    queryFn: async () => unwrap(await api.GET("/api/purchasing/inventory")),
  });
}

function useDone() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: KEY });
    void qc.invalidateQueries({ queryKey: ["planning"] }); // Planning reads stock and deliveries on order
  };
}

export function useRaisePo() {
  const done = useDone();
  return useMutation({
    mutationFn: async (body: RaisePo) =>
      unwrap(await api.POST("/api/purchasing/purchase-orders", { body })),
    onSuccess: done,
  });
}

export type PoAction =
  "approve" | "confirm" | "dispatch" | "gate-entry" | "qc" | "follow-up" | "cancel" | "edit";

/** One step on a PO: approve (owner), confirm (supplier's date), dispatch, gate entry, QC, follow-up, cancel,
 * edit (while awaiting approval). The response is the PO with its timeline. */
export function usePoAction() {
  const done = useDone();
  return useMutation({
    mutationFn: async ({
      id,
      action,
      body,
    }: {
      id: string;
      action: PoAction;
      body?: unknown;
    }): Promise<PoDetail> => {
      const path = { params: { path: { po_id: id } } };
      const P = "/api/purchasing/purchase-orders/{po_id}";
      switch (action) {
        case "approve":
          return unwrap(await api.POST(`${P}/approve`, path));
        case "confirm":
          return unwrap(
            await api.POST(`${P}/confirm`, { ...path, body: body as Schemas["ConfirmIn"] }),
          );
        case "dispatch":
          return unwrap(
            await api.POST(`${P}/dispatch`, { ...path, body: body as Schemas["DispatchIn"] }),
          );
        case "gate-entry":
          return unwrap(
            await api.POST(`${P}/gate-entry`, { ...path, body: body as Schemas["GateEntryIn"] }),
          );
        case "qc":
          return unwrap(await api.POST(`${P}/qc`, { ...path, body: body as Schemas["QcIn"] }));
        case "follow-up":
          return unwrap(
            await api.POST(`${P}/follow-up`, { ...path, body: body as Schemas["FollowUpIn"] }),
          );
        case "edit":
          return unwrap(await api.PATCH(P, { ...path, body: body as Schemas["PoEditIn"] }));
        default:
          return unwrap(
            await api.POST(`${P}/cancel`, { ...path, body: body as Schemas["CancelPoIn"] }),
          );
      }
    },
    onSuccess: done,
  });
}

/** Raw Material Purchase: every PO with its stage, KPIs and the POs that need attention. */
export function usePurchases() {
  return useQuery({
    queryKey: [...KEY, "purchases"],
    queryFn: async () => unwrap(await api.GET("/api/purchasing/purchases")),
  });
}

/** One PO with its timeline. */
export function usePo(id: string | null) {
  return useQuery({
    queryKey: [...KEY, "po", id],
    enabled: !!id,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/purchasing/purchase-orders/{po_id}", {
          params: { path: { po_id: id! } },
        }),
      ),
  });
}

/** "2.2 t", "45,000 pcs" (quantities come as decimal strings). */
export function qtyText(x: string | number, unit: string): string {
  const n = Number(x);
  return `${n.toLocaleString("en-IN", { maximumFractionDigits: 3 })} ${unit}`;
}

export const STATUS = {
  critical_short: { label: "Critical short", tone: "hi" },
  low_stock: { label: "Low stock", tone: "md" },
  in_transit: { label: "In transit", tone: "bl" },
  adequate: { label: "Adequate", tone: "ok" },
} as const;

type Tone = "md" | "bl" | "ok" | "lo" | "hi";

/** How a PO's stage reads on screen (worked out by the API from its status and dates). */
export const STAGE: Record<Po["stage"], { label: string; tone: Tone }> = {
  pending_approval: { label: "Pending approval", tone: "hi" },
  sent: { label: "PO sent", tone: "lo" },
  confirmed: { label: "Confirmed", tone: "ok" },
  in_transit: { label: "In transit", tone: "bl" },
  delayed: { label: "Delayed", tone: "hi" },
  arriving_today: { label: "Arriving today", tone: "bl" },
  at_gate: { label: "Ready for QC", tone: "md" },
  received: { label: "Received", tone: "ok" },
  cancelled: { label: "Cancelled", tone: "lo" },
};

export const PRIORITY = {
  high: { label: "High", tone: "hi" },
  medium: { label: "Medium", tone: "md" },
  low: { label: "Low", tone: "lo" },
} as const;
