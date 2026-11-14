import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";
import type { paths } from "@/api/schema";

export type Order = Schemas["OrderOut"];
export type OrderKpis = Schemas["OrderKpis"];
export type Ranking = Schemas["RankingSettings"];
export type OrderCreate = Schemas["OrderCreate"];
export type OrderUpdate = Schemas["OrderUpdate"];
export type Product = Schemas["ProductOut"];
export type CustomerOption = Schemas["CustomerOption"];
export type OrderQuery = NonNullable<paths["/api/orders"]["get"]["parameters"]["query"]>;

export const ORDER_STATUS_LABEL: Record<Order["status"], string> = {
  new: "New",
  accepted: "Accepted",
  planned: "Planned",
  in_production: "In production",
  completed: "Completed",
  shipped: "Shipped",
  cancelled: "Cancelled",
};

/** Manual status changes allowed from each status (mirrors the API's rules). */
export const NEXT_STATUSES: Record<Order["status"], Order["status"][]> = {
  new: ["accepted"],
  accepted: ["new", "planned"],
  planned: ["accepted", "in_production"],
  in_production: ["completed"],
  completed: ["shipped"],
  shipped: [],
  cancelled: [],
};

export const keys = {
  orders: (q: OrderQuery) => ["orders", "list", q] as const,
  kpis: ["orders", "kpis"] as const,
  top: ["orders", "top"] as const,
  ranking: ["orders", "ranking"] as const,
};

export async function fetchOrders(q: OrderQuery) {
  return unwrap(await api.GET("/api/orders", { params: { query: q } }));
}

export function useOrders(q: OrderQuery) {
  return useQuery({
    queryKey: keys.orders(q),
    queryFn: () => fetchOrders(q),
    placeholderData: keepPreviousData,
  });
}

export function useKpis() {
  return useQuery({
    queryKey: keys.kpis,
    queryFn: async () => unwrap(await api.GET("/api/orders/kpis")),
  });
}

export function useTopOrders() {
  return useQuery({
    queryKey: keys.top,
    queryFn: async () => unwrap(await api.GET("/api/orders/top")),
  });
}

export function useRanking() {
  return useQuery({
    queryKey: keys.ranking,
    queryFn: async () => unwrap(await api.GET("/api/orders/ranking-settings")),
  });
}

export function useProducts() {
  return useQuery({
    queryKey: ["catalog", "products"],
    queryFn: async () => unwrap(await api.GET("/api/catalog/products")),
    staleTime: 5 * 60_000,
  });
}

export function useCustomerOptions() {
  return useQuery({
    queryKey: ["customers", "options"],
    queryFn: async () => unwrap(await api.GET("/api/customers/options")),
    staleTime: 60_000,
  });
}

/** After any order change, refresh everything that shows orders. */
export function useInvalidateOrders() {
  const qc = useQueryClient();
  // Planning reads the same orders: refresh the plan too, so both screens always agree.
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["orders"] }),
      qc.invalidateQueries({ queryKey: ["planning"] }),
    ]);
}

export function useSaveRanking() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Ranking) =>
      unwrap(await api.PUT("/api/orders/ranking-settings", { body })),
    onSuccess: (data) => {
      qc.setQueryData(keys.ranking, data);
      return qc.invalidateQueries({ queryKey: keys.top });
    },
  });
}
