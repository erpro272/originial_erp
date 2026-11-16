import { Link } from "react-router-dom";
import { Tag } from "@/components/ui/Tag";

/** The deal (TXN-####) an order or PO belongs to: opens it in Billing > Invoice / E-bill. */
export function DealChip({ deal }: { deal: Record<string, string> | undefined }) {
  if (!deal?.id || !deal.number) return null;
  return (
    <Link
      to={`/billing/ebill?deal=${deal.id}`}
      onClick={(e) => e.stopPropagation()}
      className="no-underline"
    >
      <Tag tone="bl" size="sm">
        {deal.number}
      </Tag>
    </Link>
  );
}
