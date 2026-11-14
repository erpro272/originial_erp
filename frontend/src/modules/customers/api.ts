import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";
import type { paths } from "@/api/schema";
import type { TagTone } from "@/components/ui/Tag";

export type CustomerRow = Schemas["CustomerRow"];
export type CustomerPage = Schemas["CustomerPage"];
export type CustomerDetail = Schemas["CustomerDetail"];
export type CustomerIn = Schemas["CustomerIn"];
export type Health = NonNullable<CustomerRow["health"]>;
export type CustomerQuery = NonNullable<paths["/api/customers"]["get"]["parameters"]["query"]>;
export type PeriodPreset = NonNullable<CustomerQuery["period"]>;

export const HEALTH: Record<Health, { label: string; tone: TagTone; dot: string }> = {
  new: { label: "New", tone: "ok", dot: "bg-ok" },
  repeat: { label: "Repeat", tone: "lo", dot: "bg-muted" },
  high_value: { label: "High-value", tone: "bl", dot: "bg-primary" },
  declining: { label: "Declining", tone: "md", dot: "bg-md" },
  inactive: { label: "Inactive", tone: "hi", dot: "bg-hi" },
  dormant: { label: "Dormant", tone: "lo", dot: "bg-subtle" },
};
export const HEALTH_ORDER: Health[] = [
  "new",
  "repeat",
  "high_value",
  "declining",
  "inactive",
  "dormant",
];

export async function fetchCustomers(q: CustomerQuery) {
  return unwrap(await api.GET("/api/customers", { params: { query: q } }));
}

export function useCustomers(q: CustomerQuery) {
  return useQuery({
    queryKey: ["customers", "list", q],
    queryFn: () => fetchCustomers(q),
    placeholderData: keepPreviousData,
  });
}

export function useCustomer(
  id: string,
  period: Pick<CustomerQuery, "period" | "date_from" | "date_to">,
) {
  return useQuery({
    queryKey: ["customers", "detail", id, period],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/customers/{customer_id}", {
          params: { path: { customer_id: id }, query: period },
        }),
      ),
  });
}

export function useHealthSettings() {
  return useQuery({
    queryKey: ["customers", "health-settings"],
    queryFn: async () => unwrap(await api.GET("/api/customers/health-settings")),
  });
}
