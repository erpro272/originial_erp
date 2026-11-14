import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Outlet } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { PageActions } from "@/components/layout/PageActions";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { UnderlineTabs } from "@/components/ui/Tabs";
import { useKpis } from "./api";
import { OrderFormModal } from "./OrderFormModal";

/** Orders module: title, then the two tabs right under it (updated mockup). */
export function OrdersLayout() {
  const { can } = useAuth();
  const kpis = useKpis();
  const customers = useQuery({
    queryKey: ["customers", "count"],
    queryFn: async () =>
      unwrap(await api.GET("/api/customers", { params: { query: { limit: 1 } } })).overview
        .total_customers,
    staleTime: 60_000,
  });
  const [creating, setCreating] = useState(false);
  return (
    <>
      {can("orders.write") && (
        <PageActions>
          <Button onClick={() => setCreating(true)}>+ New order</Button>
        </PageActions>
      )}
      <div className="flex flex-col gap-6">
        <PageHeader title="Orders" subtitle="Every open order and the customers behind them." />
        <UnderlineTabs
          label="Orders sections"
          tabs={[
            { to: "/orders", label: "Orders received", count: kpis.data?.open_orders, end: true },
            { to: "/orders/customers", label: "Customers", count: customers.data },
          ]}
        />
      </div>
      <Outlet />
      {creating && <OrderFormModal order={null} onClose={() => setCreating(false)} />}
    </>
  );
}
