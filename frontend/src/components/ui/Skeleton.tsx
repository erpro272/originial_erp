import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cn("block animate-pulse rounded-md bg-surface-2", className)} />
  );
}

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" aria-label={label} className={cn("inline-block", className)}>
      <span className="block size-5 animate-spin rounded-full border-2 border-line border-t-primary" />
    </span>
  );
}

/** Full-area loading state. */
export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center gap-3 text-sm text-muted">
      <Spinner label={label} />
      {label}
    </div>
  );
}
