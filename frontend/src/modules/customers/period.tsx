import { useSearchParams } from "react-router-dom";
import { Button, Caret } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";
import { longDate } from "@/lib/format";
import type { PeriodPreset } from "./api";

const PRESETS: { value: PeriodPreset; label: string }[] = [
  { value: "this_month", label: "This month" },
  { value: "this_quarter", label: "This quarter" },
  { value: "fytd", label: "Financial year to date" },
  { value: "last_12_months", label: "Last 12 months" },
  { value: "custom", label: "Custom range" },
];

/** Reporting period kept in the URL, so it survives reloads and travels to a profile. */
export function usePeriod() {
  const [params, setParams] = useSearchParams();
  const preset = (params.get("period") as PeriodPreset) || "fytd";
  const date_from = params.get("from") || undefined;
  const date_to = params.get("to") || undefined;
  const set = (p: PeriodPreset, from?: string, to?: string) => {
    const next = new URLSearchParams(params);
    next.set("period", p);
    if (p === "custom" && from && to) {
      next.set("from", from);
      next.set("to", to);
    } else {
      next.delete("from");
      next.delete("to");
    }
    setParams(next, { replace: true });
  };
  const query =
    preset === "custom" && date_from && date_to
      ? { period: preset, date_from, date_to }
      : { period: preset === "custom" ? ("fytd" as const) : preset };
  return { preset, date_from, date_to, set, query, search: params.toString() };
}

const CalendarIcon = () => (
  <svg
    aria-hidden
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M16 3v4M8 3v4M3 10h18" />
  </svg>
);

export function PeriodButton({ range }: { range?: { date_from: string; date_to: string } }) {
  const p = usePeriod();
  const label = range
    ? `${longDate(range.date_from)} – ${longDate(range.date_to)}`
    : "Reporting period";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="pill" aria-label={`Reporting period: ${label}`}>
          <CalendarIcon />
          {label} <Caret />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72">
        <ul className="m-0 list-none p-0">
          {PRESETS.filter((x) => x.value !== "custom").map((x) => (
            <li key={x.value}>
              <button
                type="button"
                onClick={() => p.set(x.value)}
                className={cn(
                  "w-full cursor-pointer rounded-lg border-0 bg-transparent px-3 py-2 text-left text-sm text-ink-2 hover:bg-surface",
                  p.preset === x.value && "bg-surface font-semibold text-ink",
                )}
              >
                {x.label}
              </button>
            </li>
          ))}
        </ul>
        <form
          className="mt-2 grid grid-cols-2 gap-2 border-t border-divider pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            p.set("custom", String(f.get("from")), String(f.get("to")));
          }}
        >
          <TextField
            label="From"
            name="from"
            type="date"
            required
            defaultValue={p.date_from ?? range?.date_from}
          />
          <TextField
            label="To"
            name="to"
            type="date"
            required
            defaultValue={p.date_to ?? range?.date_to}
          />
          <Button type="submit" variant="pill" className="col-span-2">
            Apply custom range
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
