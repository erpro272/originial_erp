import { useState } from "react";
import { StatGrid } from "@/components/ui/StatGrid";
import { useKpis, type Order } from "./api";
import { OrderFormModal } from "./OrderFormModal";
import { OrdersTable } from "./OrdersTable";
import { PriorityCards } from "./PriorityCards";

export function OrdersReceivedTab() {
  const kpis = useKpis();
  const [open, setOpen] = useState<Order | null>(null);
  const k = kpis.data;
  return (
    <>
      <StatGrid
        loading={kpis.isPending}
        items={[
          { label: "Open orders", value: k?.open_orders ?? "—" },
          { label: "High priority", value: k?.high_priority ?? "—", tone: "hi" },
          { label: "In production", value: k?.in_production ?? "—", tone: "bl" },
          { label: "Ship in 7 days", value: k?.ship_in_7_days ?? "—", tone: "md" },
        ]}
      />
      <PriorityCards onOpen={setOpen} />
      <OrdersTable onOpen={setOpen} />
      {open && <OrderFormModal order={open} onClose={() => setOpen(null)} />}
    </>
  );
}
