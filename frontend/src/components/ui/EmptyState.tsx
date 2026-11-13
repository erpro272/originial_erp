import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Dashed empty/locked panel, as in planning.html "No plan generated yet". */
export function EmptyState({
  icon,
  title,
  description,
  actions,
  className,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex flex-col items-center gap-3.5 rounded-card border border-dashed border-faint bg-surface px-6 py-16 text-center",
        className,
      )}
    >
      {icon && (
        <span className="grid size-11 place-items-center rounded-full bg-bl-bg text-primary">
          {icon}
        </span>
      )}
      <h2 className="m-0 text-xl font-semibold">{title}</h2>
      {description && <p className="m-0 max-w-[460px] text-[15px] text-muted">{description}</p>}
      {actions && <div className="mt-1.5 flex flex-wrap justify-center gap-2.5">{actions}</div>}
    </section>
  );
}

/** Inline error state with a retry. */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="grid size-10 place-items-center rounded-full bg-hi-bg font-bold text-hi">
        !
      </span>
      <p className="m-0 text-sm text-ink-2">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="cursor-pointer text-sm font-medium text-link"
        >
          Try again
        </button>
      )}
    </div>
  );
}
