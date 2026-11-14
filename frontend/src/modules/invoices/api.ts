import { useQuery } from "@tanstack/react-query";
import { ApiError, api, apiFetch, unwrap, type Schemas } from "@/api/client";
import type { TagTone } from "@/components/ui/Tag";

export type Upload = Schemas["UploadOut"];
export type UploadDetail = Schemas["UploadDetail"];
export type Batch = Schemas["BatchOut"];

export interface Cell {
  raw: string | null;
  value: unknown;
  confidence: number | null;
  page: number | null;
  bbox: [number, number, number, number] | null;
  edited?: boolean;
  masked?: boolean;
}
export interface Doc {
  is_invoice?: boolean;
  fields: Record<string, Cell>;
  lines: Record<string, Cell>[];
  qr: Record<string, unknown> | null;
}
export interface Check {
  id: string;
  code: string;
  severity: "error" | "warning";
  path: string;
  message: string;
}
export interface MatchCandidate {
  customer_id: string;
  name: string;
  gstin: string | null;
  score: number;
  reasons: string[];
  gstin_conflict: boolean;
}
export interface Match {
  kind: "existing" | "new" | "ambiguous";
  customer_id: string | null;
  candidates: MatchCandidate[];
  message: string;
  prefill: Schemas["CustomerIn"];
}
export interface FieldSpec {
  sections: { key: string; label: string }[];
  fields: { key: string; label: string; section: string; type: string }[];
  line_fields: { key: string; label: string; type: string }[];
}

export const STATUS: Record<Upload["status"], { label: string; tone: TagTone }> = {
  uploaded: { label: "Queued", tone: "lo" },
  extracting: { label: "Reading…", tone: "bl" },
  needs_review: { label: "Needs review", tone: "md" },
  verified: { label: "Verified", tone: "bl" },
  saved: { label: "Saved", tone: "ok" },
  failed: { label: "Failed", tone: "hi" },
  rejected: { label: "Rejected", tone: "lo" },
};

export const ACCEPT =
  ".jpg,.jpeg,.png,.heic,.heif,.pdf,image/jpeg,image/png,image/heic,application/pdf";
export const MAX_MB = 20;

export async function uploadFiles(files: File[]): Promise<Batch> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f, f.name));
  const res = await apiFetch("/api/invoices/uploads", { method: "POST", body: form });
  const body = await res.json().catch(() => ({}));
  if (!res.ok)
    throw new ApiError(
      res.status,
      body?.error?.code ?? "error",
      body?.error?.message ?? "Upload failed.",
      body?.error?.details ?? {},
    );
  return body as Batch;
}

export function useUploads(params: { batch_id?: string; status?: string[] }, poll = true) {
  return useQuery({
    queryKey: ["invoices", "uploads", params],
    queryFn: async () =>
      unwrap(await api.GET("/api/invoices/uploads", { params: { query: params } })),
    refetchInterval: (q) =>
      poll && q.state.data?.items.some((u) => u.status === "uploaded" || u.status === "extracting")
        ? 1500
        : false,
  });
}

export function useFieldSpec() {
  return useQuery({
    queryKey: ["invoices", "field-spec"],
    queryFn: async () => unwrap(await api.GET("/api/invoices/field-spec")) as unknown as FieldSpec,
    staleTime: Infinity,
  });
}

export function pct(c: number | null | undefined): string {
  return c == null ? "—" : `${Math.round(c * 100)}%`;
}
