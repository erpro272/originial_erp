import { useLocation } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { UnderlineTabs } from "@/components/ui/Tabs";
import { EbillTab } from "./EbillTab";
import { PaymentsTab } from "./PaymentsTab";

/** Billing: Payments & Settlements, Invoice / E-bill (deals), GST filing (next round). */
export function BillingPage() {
  const { pathname } = useLocation();
  const section = pathname.endsWith("/ebill")
    ? "ebill"
    : pathname.endsWith("/gst")
      ? "gst"
      : "payments";
  return (
    <div className="flex flex-col gap-7">
      <PageHeader
        title="Billing"
        subtitle="Track what customers owe you and what you owe suppliers, in one place."
      />
      <UnderlineTabs
        label="Billing sections"
        tabs={[
          { to: "/billing", label: "Payments", end: true },
          { to: "/billing/ebill", label: "Invoice / E-bill" },
          { to: "/billing/gst", label: "GST filing" },
        ]}
      />
      {section === "payments" && <PaymentsTab />}
      {section === "ebill" && <EbillTab />}
      {section === "gst" && (
        <section className="flex flex-col items-center gap-3 rounded-card border border-dashed border-faint bg-surface px-6 py-16 text-center">
          <h2 className="m-0 text-xl font-semibold">GST filing · coming next</h2>
          <p className="m-0 max-w-[480px] text-[15px] text-muted">
            It will read the same issued tax invoices (and supplier invoices for input credit) as
            Payments and Invoice / E-bill.
          </p>
        </section>
      )}
    </div>
  );
}
