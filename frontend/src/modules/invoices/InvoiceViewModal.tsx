import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { Modal } from "@/components/ui/Modal";
import { LoadingState } from "@/components/ui/Skeleton";
import { longDate, qty, rupees } from "@/lib/format";

type Row = Record<string, unknown>;
const r = (v: unknown) => (typeof v === "number" ? `₹${rupees(v)}` : "—");

/** A saved invoice, read-only, with a link to the original uploaded file. */
export function InvoiceViewModal({
  invoiceId,
  onClose,
}: {
  invoiceId: string;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["invoices", "view", invoiceId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/invoices/{invoice_id}", {
          params: { path: { invoice_id: invoiceId } },
        }),
      ),
  });
  const inv = q.data?.invoice as Row | undefined;
  const buyer = q.data?.parties.find((p) => p.role === "buyer") as Row | undefined;
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      width={760}
      title={inv ? `Invoice ${String(inv.invoice_number ?? "")}` : "Invoice"}
      description={
        inv ? `${longDate(inv.invoice_date as string)} · ${String(buyer?.name ?? "")}` : undefined
      }
    >
      {q.isPending ? (
        <LoadingState />
      ) : q.data && inv ? (
        <div className="flex flex-col gap-4 text-sm">
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
            {[
              ["Grand total", r(inv.grand_total_paise)],
              ["Taxable", r(inv.total_taxable_paise)],
              ["Balance due", r(inv.balance_due_paise)],
              [
                "CGST + SGST",
                inv.total_cgst_paise
                  ? `${r(inv.total_cgst_paise)} + ${r(inv.total_sgst_paise)}`
                  : "—",
              ],
              ["IGST", r(inv.total_igst_paise)],
              [
                "Supply",
                inv.supply_type === "intra"
                  ? "Intra-state"
                  : inv.supply_type === "inter"
                    ? "Inter-state"
                    : "—",
              ],
              ["Buyer GSTIN", String(inv.buyer_gstin ?? "—")],
              ["Due date", longDate(inv.due_date as string | null)],
              ["IRN", inv.irn ? `${String(inv.irn).slice(0, 16)}…` : "—"],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-muted">{k}</dt>
                <dd className="m-0 font-medium">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="overflow-x-auto rounded-xl border border-divider">
            <table className="w-full border-collapse">
              <thead className="bg-surface">
                <tr>
                  {["Product", "HSN", "Qty", "Rate", "Taxable", "Total"].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left text-xs font-semibold tracking-[.04em] text-muted uppercase"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {q.data.lines.map((l) => (
                  <tr key={String(l.id)}>
                    <td className="border-t border-divider px-3 py-2">
                      {String(l.product_name ?? "—")}
                    </td>
                    <td className="border-t border-divider px-3 py-2">{String(l.hsn ?? "—")}</td>
                    <td className="border-t border-divider px-3 py-2">
                      {l.quantity ? `${qty(String(l.quantity))} ${String(l.uom ?? "")}` : "—"}
                    </td>
                    <td className="border-t border-divider px-3 py-2">{r(l.unit_price_paise)}</td>
                    <td className="border-t border-divider px-3 py-2">{r(l.taxable_paise)}</td>
                    <td className="border-t border-divider px-3 py-2">{r(l.total_paise)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {q.data.payment && (
            <p className="m-0 text-muted">
              Bank: {String(q.data.payment.bank_name ?? "—")} · A/c{" "}
              {String(q.data.payment.bank_account ?? "—")}
              {!q.data.payment.sensitive_visible && " (masked for your role)"}
            </p>
          )}
          {q.data.transport && (
            <p className="m-0 text-muted">
              Transport: {String(q.data.transport.transporter_name ?? "—")} · Vehicle{" "}
              {String(q.data.transport.vehicle_no ?? "—")} · E-way bill{" "}
              {String(q.data.transport.eway_bill_no ?? "—")}
            </p>
          )}
          {q.data.original_url && (
            <a
              href={q.data.original_url}
              target="_blank"
              rel="noreferrer"
              className="self-start font-medium"
            >
              Open the original file ↗
            </a>
          )}
        </div>
      ) : (
        <p className="m-0 text-sm text-hi">Couldn't load this invoice.</p>
      )}
    </Modal>
  );
}
