import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type ArOut = Schemas["ArOut"];
export type ArRow = Schemas["ArRow"];
export type ArCustomer = Schemas["ArCustomer"];
export type ArInvoice = Schemas["ArInvoice"];
export type ApOut = Schemas["ApOut"];
export type ApRow = Schemas["ApRow"];
export type ApSupplier = Schemas["ApSupplier"];
export type ApInvoice = Schemas["ApInvoice"];
export type DealsOut = Schemas["DealsOut"];
export type DealRow = Schemas["DealRow"];
export type DealDetail = Schemas["DealDetail"];
export type Interaction = Schemas["InteractionOut"];

const KEY = ["billing"] as const;

/** Every write changes numbers on several screens: refresh all of Billing (and Orders / Purchasing chips). */
function useDone() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: KEY });
    void qc.invalidateQueries({ queryKey: ["customers"] });
  };
}

export function useReceivables(month: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "ar", month],
    queryFn: async () =>
      unwrap(await api.GET("/api/billing/receivables", { params: { query: { month } } })),
  });
}

export function useArCustomer(id: string | null, month: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "ar", "customer", id, month],
    enabled: !!id,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/billing/receivables/customers/{customer_id}", {
          params: { path: { customer_id: id! }, query: { month } },
        }),
      ),
  });
}

export function usePayables(month: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "ap", month],
    queryFn: async () =>
      unwrap(await api.GET("/api/billing/payables", { params: { query: { month } } })),
  });
}

export function useApSupplier(id: string | null, month: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "ap", "supplier", id, month],
    enabled: !!id,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/billing/payables/suppliers/{supplier_id}", {
          params: { path: { supplier_id: id! }, query: { month } },
        }),
      ),
  });
}

export function useDeals(month: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "deals", month],
    queryFn: async () =>
      unwrap(await api.GET("/api/billing/deals", { params: { query: { month } } })),
  });
}

export function useDeal(id: string | null) {
  return useQuery({
    queryKey: [...KEY, "deal", id],
    enabled: !!id,
    queryFn: async () =>
      unwrap(await api.GET("/api/billing/deals/{deal_id}", { params: { path: { deal_id: id! } } })),
  });
}

/** Any Billing action: one mutation, the call is passed in (each is typed at the call site). */
export function useBillingAction<T>() {
  const done = useDone();
  return useMutation({ mutationFn: async (call: () => Promise<T>) => call(), onSuccess: done });
}

/** The CSV of the filtered table, generated (and logged) by the server. */
export async function downloadCsv(
  mode: "ar" | "ap",
  month: string | undefined,
  status: string,
  q: string,
) {
  const path = mode === "ar" ? "/api/billing/receivables/export" : "/api/billing/payables/export";
  const res = await api.GET(path, {
    params: { query: { month, status: status === "all" ? undefined : status, q: q || undefined } },
    parseAs: "blob",
  });
  const blob = res.data as unknown as Blob;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${mode === "ar" ? "receivables" : "payables"}-${month ?? "current"}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** The last 15 months, newest first (the period selector). */
export function months(today: Date = new Date()): { value: string; label: string }[] {
  const out = [];
  for (let i = 0; i < 15; i++) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
    out.push({ value, label: i === 0 ? `${label} (to date)` : label });
  }
  return out;
}

export const AR_STATUS = {
  overdue: { label: "Overdue", tone: "hi" },
  due_week: { label: "Due this week", tone: "md" },
  promise: { label: "Promise made", tone: "bl" },
  not_due: { label: "Not yet due", tone: "lo" },
} as const;

export const AP_STATUS = {
  pending_verif: { label: "Pending verification", tone: "md" },
  pending_owner: { label: "Pending owner approval", tone: "md" },
  approved: { label: "Approved", tone: "bl" },
  scheduled: { label: "Scheduled", tone: "bl" },
  paid: { label: "Paid", tone: "ok" },
  on_hold: { label: "On hold", tone: "lo" },
  rejected: { label: "Rejected", tone: "hi" },
} as const;

export const STEPS = [
  "Invoice received",
  "Accounts verification",
  "Owner approval",
  "Payment scheduling",
  "Payment execution",
  "Bank confirmation",
  "Settlement completed",
];

export const DEAL_TONE: Record<string, "hi" | "md" | "lo" | "ok" | "bl"> = {
  "Enquiry Received": "lo",
  "Awaiting Response": "md",
  Negotiation: "md",
  "Order Confirmed": "bl",
  Processing: "bl",
  "Partially Dispatched": "bl",
  Dispatched: "bl",
  "Invoice Pending": "md",
  Invoiced: "bl",
  "Partially Settled": "md",
  Completed: "ok",
  "On Hold": "hi",
  Cancelled: "lo",
};

/** "₹4,07,78,149" (Indian grouping, whole rupees). */
export function inr(paise: number): string {
  return `${paise < 0 ? "-" : ""}₹${Math.round(Math.abs(paise) / 100).toLocaleString("en-IN")}`;
}

/** Order / PO -> its deal (TXN chip). Only for roles that can see Billing; one request per page. */
export function useDealRefs(kind: "order" | "po", ids: string[], enabled: boolean) {
  return useQuery({
    queryKey: [...KEY, "refs", kind, ids],
    enabled: enabled && ids.length > 0,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/billing/deal-refs", {
          params: { query: kind === "order" ? { order_id: ids } : { po_id: ids } },
        }),
      ),
  });
}
