import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import type { Plan } from "./api";
import { RuleButton } from "./RuleButton";

/** Approved plan: what changed since its last approved version, and why. Significant changes make the
 * revision that needs re-approval; the rest is information. */
export function RevisionPanel({ plan }: { plan: Plan }) {
  const rv = plan.revision;
  if (!rv || rv.changes.length === 0) return null;
  return (
    <section
      aria-label="What changed"
      className={cn(
        "flex flex-col gap-4 rounded-card border bg-surface px-6 py-5",
        rv.needed ? "border-hi-line" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="m-0 text-[17px] font-semibold">
          What changed since approved version v{rv.against}
        </h3>
        {rv.needed ? (
          <Tag tone="hi">Rev {rv.number} needs re-approval</Tag>
        ) : (
          <Tag tone="ok">No re-approval needed</Tag>
        )}
      </div>
      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {rv.changes.map((c, i) => (
          <li
            key={i}
            className="flex flex-col gap-1 border-t border-line pt-3 first:border-0 first:pt-0"
          >
            <span className="flex flex-wrap items-center gap-2 text-sm">
              <Tag tone={c.significant ? "hi" : "lo"} size="sm">
                {c.significant ? "Needs re-approval" : "For information"}
              </Tag>
              <b className="font-semibold">{c.title}</b>
            </span>
            {c.why.length > 0 && (
              <span className="text-[13px] text-muted">Why: {c.why.join("; ")}</span>
            )}
          </li>
        ))}
      </ul>
      <p className="m-0 flex items-center gap-1.5 text-[13px] text-muted">
        Re-approval is asked for later or late deliveries, new material shortages, machines over
        capacity, changed or cancelled orders, and a contribution drop above your limit.
        <RuleButton rule="reapproval" />
      </p>
    </section>
  );
}
