import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

export interface UnderlineTab {
  to: string;
  label: string;
  count?: number;
  end?: boolean;
}

/** Underline tabs inside a module ("Orders received 12 | Customers 8"). Router-driven. */
export function UnderlineTabs({
  tabs,
  right,
  label,
}: {
  tabs: UnderlineTab[];
  right?: ReactNode;
  label: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line">
      <nav aria-label={label} className="flex gap-7">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              cn(
                "-mb-px border-b-2 border-transparent py-2.5 text-[15px] text-ink-3 no-underline hover:text-ink",
                isActive && "border-ink font-semibold text-ink",
              )
            }
          >
            {t.label}
            {t.count !== undefined && (
              <span className="ml-1 font-medium text-muted">{t.count}</span>
            )}
          </NavLink>
        ))}
      </nav>
      {right && <div className="flex flex-wrap gap-2 pb-2">{right}</div>}
    </div>
  );
}

export interface Step {
  id: string;
  label: string;
  locked?: boolean;
  /** Shows a dot: "this tab changed since you last looked" (Plan updated · N tabs changed). */
  changed?: boolean;
}

/** Numbered step tabs (Planning: 1 Selected orders … 6 Final plan approval). */
export function StepTabs({
  steps,
  active,
  onSelect,
  label,
}: {
  steps: Step[];
  active: string;
  onSelect: (id: string) => void;
  label: string;
}) {
  return (
    <nav
      aria-label={label}
      className="flex gap-7 overflow-x-auto border-b border-line"
      role="tablist"
    >
      {steps.map((s, i) => {
        const on = s.id === active;
        return (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={on}
            aria-disabled={s.locked || undefined}
            onClick={() => onSelect(s.id)}
            className={cn(
              "relative -mb-px flex cursor-pointer items-center gap-2 border-0 border-b-2 border-transparent bg-transparent px-0 pt-2.5 pb-3 text-[15px] whitespace-nowrap text-ink-3",
              on && "border-ink font-semibold text-ink",
              s.locked && "text-subtle",
            )}
          >
            <span
              className={cn(
                "grid size-[22px] place-items-center rounded-full border border-faint text-xs font-semibold text-muted",
                on && "border-ink bg-ink text-white",
                s.locked && "border-dashed text-subtle",
              )}
            >
              {i + 1}
            </span>
            {s.label}
            {s.changed && <span aria-label="changed" className="size-2 rounded-full bg-primary" />}
          </button>
        );
      })}
    </nav>
  );
}
