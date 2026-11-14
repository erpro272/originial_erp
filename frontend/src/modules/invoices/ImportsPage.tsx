import { useQueryClient } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api, unwrap } from "@/api/client";
import { DataTable } from "@/components/data-table/DataTable";
import { FilterChips } from "@/components/ui/FilterChips";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { dateTime, rupees } from "@/lib/format";
import { pct, STATUS, useUploads, type Upload } from "./api";
import { MockNotice, UploadInvoiceButton } from "./UploadInvoiceDialog";

const h = createColumnHelper<Upload>();
type Filter = "all" | "review" | "saved" | "failed";
const FILTER_STATUS: Record<Filter, string[] | undefined> = {
  all: undefined,
  review: ["needs_review", "verified"],
  saved: ["saved"],
  failed: ["failed", "rejected"],
};

export function ImportsPage() {
  const [filter, setFilter] = useState<Filter>("review");
  const q = useUploads({ status: FILTER_STATUS[filter] });
  const all = useUploads({});
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast } = useToast();
  const counts = all.data?.counts ?? {};
  const retry = async (u: Upload) => {
    try {
      unwrap(
        await api.POST("/api/invoices/uploads/{upload_id}/retry", {
          params: { path: { upload_id: u.id } },
        }),
      );
      await qc.invalidateQueries({ queryKey: ["invoices"] });
      toast({ title: `Reading ${u.file_name} again`, tone: "default" });
    } catch (e) {
      toast({
        title: "Couldn't retry",
        description: e instanceof ApiError ? e.message : undefined,
        tone: "error",
      });
    }
  };
  const columns = useMemo(
    () => [
      h.accessor("file_name", {
        id: "file",
        header: "File",
        meta: { label: "File", alwaysVisible: true },
      }),
      h.accessor("status", {
        id: "status",
        header: "Status",
        cell: (c) => <Tag tone={STATUS[c.getValue()].tone}>{STATUS[c.getValue()].label}</Tag>,
        meta: { label: "Status" },
      }),
      h.accessor((u) => u.buyer_name ?? "", {
        id: "buyer",
        header: "Customer on invoice",
        cell: (c) => c.getValue() || "—",
        meta: { label: "Customer on invoice" },
      }),
      h.accessor((u) => u.invoice_number ?? "", {
        id: "number",
        header: "Invoice no.",
        cell: (c) => <span className="font-mono text-[13px]">{c.getValue() || "—"}</span>,
        meta: { label: "Invoice no." },
      }),
      h.accessor("grand_total_paise", {
        id: "total",
        header: "Total (₹)",
        cell: (c) => (c.getValue() == null ? "—" : rupees(c.getValue()!)),
        meta: { label: "Total (₹)", align: "right" },
      }),
      h.accessor("overall_confidence", {
        id: "confidence",
        header: "Read confidence",
        cell: (c) => pct(c.getValue()),
        meta: { label: "Read confidence", align: "right" },
      }),
      h.accessor("customer_action", {
        id: "customer_action",
        header: "Customer",
        cell: (c) =>
          c.getValue() === "new" ? "New customer" : c.getValue() === "existing" ? "Existing" : "—",
        meta: { label: "Customer match" },
      }),
      h.accessor((u) => u.uploaded_by_name ?? "", {
        id: "by",
        header: "Uploaded by",
        meta: { label: "Uploaded by", defaultHidden: true },
      }),
      h.accessor("created_at", {
        id: "at",
        header: "Uploaded",
        cell: (c) => dateTime(c.getValue()),
        meta: { label: "Uploaded" },
      }),
      h.display({
        id: "action",
        header: "",
        cell: (c) => {
          const u = c.row.original;
          if (u.status === "failed")
            return (
              <button
                type="button"
                onClick={(e) => (e.stopPropagation(), retry(u))}
                className="cursor-pointer border-0 bg-transparent font-medium text-link"
              >
                Try again
              </button>
            );
          return u.status === "needs_review" || u.status === "verified" ? (
            <span className="font-medium text-link">Review →</span>
          ) : null;
        },
        meta: { label: "Action", alwaysVisible: true },
      }),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <Link to="/orders/customers" className="text-sm font-medium no-underline">
            ← Customers
          </Link>
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Invoice imports</h2>
          <p className="m-0 text-[15px] text-muted">
            Uploaded invoices are read automatically, then wait here until you check and save them.
          </p>
        </div>
        <UploadInvoiceButton />
      </div>
      {all.data?.items.some((u) => u.ai_mode === "mock") && <MockNotice />}
      <FilterChips
        label="Filter imports"
        value={filter}
        onChange={setFilter}
        options={[
          {
            value: "review" as const,
            label: "Need review",
            count: (counts.needs_review ?? 0) + (counts.verified ?? 0),
            dot: "bg-md-accent",
          },
          { value: "saved" as const, label: "Saved", count: counts.saved ?? 0, dot: "bg-ok" },
          {
            value: "failed" as const,
            label: "Failed or rejected",
            count: (counts.failed ?? 0) + (counts.rejected ?? 0),
            dot: "bg-hi",
          },
          {
            value: "all" as const,
            label: "All",
            count: Object.values(counts).reduce((a, b) => a + b, 0),
          },
        ]}
      />
      <DataTable<Upload>
        tableId="invoice-imports"
        title="Uploads"
        columns={columns}
        data={q.data?.items ?? []}
        getRowId={(u) => u.id}
        loading={q.isPending}
        error={q.isError ? (q.error as Error).message : null}
        onRetry={() => q.refetch()}
        onRowClick={(u) =>
          u.status === "saved" && u.invoice_id
            ? undefined
            : navigate(`/orders/customers/imports/${u.id}`)
        }
        empty={{
          title: filter === "review" ? "Nothing waiting for review" : "No uploads here",
          description: "Upload photos, scans or PDFs of invoices to add them.",
        }}
      />
    </>
  );
}
