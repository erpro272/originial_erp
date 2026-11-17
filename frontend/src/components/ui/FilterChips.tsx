import { cn } from "@/lib/cn";

export interface ChipOption<T extends string> {
  value: T;
  label: string;
  count?: number;
  /** Tailwind bg-* class for the small dot. */
  dot?: string;
}

/** Filter chips with counts (customer health). Selected chip is dark filled. */
export function FilterChips<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: ChipOption<T>[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-line-input bg-card px-3.5 py-[7px] text-[13px] font-medium text-ink-2 hover:border-faint",
              on && "border-inverse bg-inverse text-on-inverse hover:border-inverse",
            )}
          >
            {o.dot && <i aria-hidden className={cn("size-2 rounded-full", o.dot)} />}
            {o.label}
            {o.count !== undefined && (
              <em className={cn("not-italic", on ? "text-faint" : "text-muted")}>
                {o.count.toLocaleString("en-IN")}
              </em>
            )}
          </button>
        );
      })}
    </div>
  );
}
