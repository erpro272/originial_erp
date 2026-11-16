import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type Inventory = Schemas["InventoryOut"];
export type MaterialRow = Schemas["MaterialRow"];
export type Po = Schemas["PoOut"];
export type RaisePo = Schemas["PoRaiseIn"];

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

type Action = "approve" | "confirm" | "receive" | "cancel";

/** approve (owner) / confirm (supplier's date) / receive (qty) / cancel (reason) */
export function usePoAction() {
  const done = useDone();
  return useMutation({
    mutationFn: async ({ id, action, body }: { id: string; action: Action; body?: unknown }) => {
      const path = { params: { path: { po_id: id } } };
      if (action === "approve")
        return unwrap(await api.POST("/api/purchasing/purchase-orders/{po_id}/approve", path));
      if (action === "confirm")
        return unwrap(
          await api.POST("/api/purchasing/purchase-orders/{po_id}/confirm", {
            ...path,
            body: body as Schemas["ConfirmIn"],
          }),
        );
      if (action === "receive")
        return unwrap(
          await api.POST("/api/purchasing/purchase-orders/{po_id}/receive", {
            ...path,
            body: body as Schemas["ReceiveIn"],
          }),
        );
      return unwrap(
        await api.POST("/api/purchasing/purchase-orders/{po_id}/cancel", {
          ...path,
          body: body as Schemas["CancelPoIn"],
        }),
      );
    },
    onSuccess: done,
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

export const PO_STATUS: Record<string, { label: string; tone: "md" | "bl" | "ok" | "lo" | "hi" }> =
  {
    awaiting_approval: { label: "Awaiting approval", tone: "md" },
    ordered: { label: "Ordered", tone: "bl" },
    confirmed: { label: "Confirmed", tone: "ok" },
    received: { label: "Received", tone: "lo" },
    cancelled: { label: "Cancelled", tone: "lo" },
  };
