import { useMemo, useState } from "react";
import { Button, Caret } from "./Button";
import { Popover, PopoverContent, PopoverTrigger } from "./Menu";

export interface MultiOption {
  value: string;
  label: string;
  hint?: string;
}

/** "All customers ▾": pick several values from a searchable checkbox list. */
export function MultiSelect({
  label,
  allLabel,
  options,
  value,
  onChange,
  searchable = true,
}: {
  label: string;
  allLabel: string;
  options: MultiOption[];
  value: string[];
  onChange: (v: string[]) => void;
  searchable?: boolean;
}) {
  const [q, setQ] = useState("");
  const shown = useMemo(
    () => options.filter((o) => o.label.toLowerCase().includes(q.trim().toLowerCase())),
    [options, q],
  );
  const text =
    value.length === 0
      ? allLabel
      : value.length === 1
        ? (options.find((o) => o.value === value[0])?.label ?? `${label}: 1`)
        : `${label}: ${value.length}`;
  const toggle = (v: string) =>
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="pill"
          aria-label={`${label} filter`}
          className={value.length ? "border-faint text-ink" : ""}
        >
          <span className="max-w-40 truncate">{text}</span> <Caret />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72">
        {searchable && (
          <input
            aria-label={`Search ${label.toLowerCase()}`}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search"
            className="mb-2 w-full rounded-lg border border-line-input px-3 py-2 text-sm outline-none focus:border-primary"
          />
        )}
        <ul className="m-0 max-h-72 list-none overflow-y-auto p-0">
          {shown.map((o) => (
            <li key={o.value}>
              <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-ink-2 hover:bg-surface">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={value.includes(o.value)}
                  onChange={() => toggle(o.value)}
                />
                <span className="flex-1 truncate">{o.label}</span>
                {o.hint && <span className="text-xs text-subtle">{o.hint}</span>}
              </label>
            </li>
          ))}
          {shown.length === 0 && <li className="px-2 py-3 text-sm text-muted">No matches</li>}
        </ul>
        {value.length > 0 && (
          <div className="mt-2 flex justify-between border-t border-divider px-2 pt-2 text-xs">
            <span className="text-muted">{value.length} selected</span>
            <button
              type="button"
              onClick={() => onChange([])}
              className="cursor-pointer border-0 bg-transparent font-medium text-link"
            >
              Clear
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
