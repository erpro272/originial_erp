import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Briefly highlights its content whenever `value` changes (after a recalculation). */
export function Flash({ value, children }: { value: unknown; children?: ReactNode }) {
  const key = JSON.stringify(value);
  const [seen, setSeen] = useState({ key, n: 0 });
  if (seen.key !== key) setSeen({ key, n: seen.n + 1 }); // changed since last render: replay the highlight
  return (
    <span key={seen.n} className={cn("rounded-[4px]", seen.n > 0 && "animate-flash")}>
      {children ?? String(value)}
    </span>
  );
}
