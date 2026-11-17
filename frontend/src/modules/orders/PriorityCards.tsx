import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/Button";
import { Card, SectionLabel } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { qty, rupeesCompact, shortDate } from "@/lib/format";
import { useTopOrders, type Order } from "./api";
import { RankingSettingsButton } from "./RankingSettings";

const PRIORITY_TONE: Record<Order["priority"], TagTone> = { high: "hi", medium: "md", low: "lo" };
const PRIORITY_LABEL: Record<Order["priority"], string> = {
  high: "High priority",
  medium: "Medium priority",
  low: "Low priority",
};
const SIGNAL_TEXT: Record<string, string> = {
  hi: "text-hi",
  md: "text-md",
  ok: "text-ok",
  bl: "text-bl",
  lo: "text-muted",
};

export function PriorityCard({ o, onOpen }: { o: Order; onOpen: (o: Order) => void }) {
  const accent = o.signal.tone === "hi" ? "hi" : o.signal.tone === "md" ? "md" : "none";
  return (
    <Card
      accent={accent}
      className="flex cursor-pointer flex-col gap-3.5 p-[22px] transition-shadow hover:shadow-lift"
      onClick={() => onOpen(o)}
      role="button"
      tabIndex={0}
      aria-label={`Open ${o.number}`}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpen(o);
      }}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-semibold">{o.number}</span>
        <Tag tone={PRIORITY_TONE[o.priority]}>{PRIORITY_LABEL[o.priority]}</Tag>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-lg font-semibold">{o.product_name}</span>
        <span className="text-sm text-muted">
          {o.customer_name} · {qty(o.quantity)} {o.unit} · ships {shortDate(o.ship_date)}
        </span>
      </div>
      <div className="flex flex-wrap gap-6 text-sm text-ink-2">
        <span>
          Sales <b>{rupeesCompact(o.sales_paise)}</b>
        </span>
        <span>
          Profit <b>{rupeesCompact(o.profit_paise)}</b>
        </span>
        <span>{o.processing_days} days</span>
      </div>
      <div className="mt-auto flex items-center justify-between gap-3 border-t border-divider pt-3.5">
        <span className={cn("text-sm", SIGNAL_TEXT[o.signal.tone])}>{o.signal.text}</span>
        {o.signal.action && (
          <Link
            to={o.signal.action.href}
            onClick={(e) => e.stopPropagation()}
            className={cn(
              buttonVariants({ variant: "dark", size: "sm" }),
              "min-h-9 no-underline hover:text-on-inverse",
            )}
          >
            {o.signal.action.label}
          </Link>
        )}
      </div>
    </Card>
  );
}

export function PriorityCards({ onOpen }: { onOpen: (o: Order) => void }) {
  const top = useTopOrders();
  return (
    <section className="flex flex-col gap-3.5" aria-label="Needs attention">
      <div className="flex items-center justify-between gap-3">
        <SectionLabel>Needs attention</SectionLabel>
        <RankingSettingsButton />
      </div>
      {top.isError ? (
        <ErrorState message="Couldn't load the priority orders." onRetry={() => top.refetch()} />
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {top.isPending
            ? [0, 1, 2].map((i) => (
                <Card key={i} className="flex flex-col gap-4 p-[22px]">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-5 w-40" />
                  <Skeleton className="h-4 w-56" />
                  <Skeleton className="h-4 w-48" />
                </Card>
              ))
            : top.data.map((o) => <PriorityCard key={o.id} o={o} onOpen={onOpen} />)}
          {top.data?.length === 0 && (
            <p className="col-span-3 m-0 text-sm text-muted">
              No open orders. New orders will appear here.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
