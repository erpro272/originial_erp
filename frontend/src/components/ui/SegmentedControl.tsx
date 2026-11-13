import { cn } from "@/lib/cn";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
}

/** Pill segmented control ("Original plan | Plan comparison", "Current | Past"). */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  size = "md",
  className,
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  size?: "md" | "sm";
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn(
        "inline-flex rounded-full border border-line bg-surface",
        size === "md" ? "p-1" : "p-[3px]",
        className,
      )}
      onKeyDown={(e) => {
        const i = options.findIndex((o) => o.value === value);
        const next =
          e.key === "ArrowRight"
            ? options[(i + 1) % options.length]
            : e.key === "ArrowLeft"
              ? options[(i - 1 + options.length) % options.length]
              : undefined;
        if (next) {
          e.preventDefault();
          onChange(next.value);
        }
      }}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cn(
              "cursor-pointer rounded-full border-0 bg-transparent font-medium text-ink-3",
              size === "md" ? "px-[18px] py-2 text-sm" : "px-3.5 py-1.5 text-[13px]",
              on && "bg-white font-semibold text-ink shadow-seg",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
