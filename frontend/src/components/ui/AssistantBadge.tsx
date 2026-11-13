import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** "✦ Planning assistant" badge (purple), used wherever AI suggestions appear. */
export function AssistantBadge({
  children = "Assistant",
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-ai-bg px-2.5 py-1 text-xs font-semibold whitespace-nowrap text-ai",
        className,
      )}
    >
      <span aria-hidden>✦</span>
      {children}
    </span>
  );
}

/** Purple-washed callout with the badge, e.g. the plan comparison "✦ Summary". */
export function AssistantCallout({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <section className="flex items-start gap-3.5 rounded-card border border-ai-line bg-ai-wash px-[22px] py-[18px]">
      <AssistantBadge className="flex-none">{label}</AssistantBadge>
      <div className="text-sm leading-relaxed text-ink-2">{children}</div>
    </section>
  );
}
