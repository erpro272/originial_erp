import { useState, type CSSProperties, type ReactNode } from "react";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { OPT_LABEL, type OptKey, type Selection } from "./api";
import { addDays, dayParts, daysBetween, plural, range } from "./format";

const LABEL_W = 200;
const DAY_MIN = 42;
const MAX_DAYS = 120;

/**
 * Order timeline (mockup "Order timeline"): running orders vs. the 3 selection options, one bar per
 * order with its machine route. Updates with every tick in the table below (the server recalculates).
 */
export function OrderTimeline({
  selection,
  today,
  focus,
  onFocus,
}: {
  selection: Selection;
  today: string;
  focus: OptKey;
  onFocus: (k: OptKey) => void;
}) {
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(addDays(today, 20)); // 3 weeks
  const days = daysBetween(from, to).slice(0, MAX_DAYS);
  const last = days[days.length - 1] ?? to;
  const col = (iso: string) => days.indexOf(iso) + 2;
  const grid: CSSProperties = {
    gridTemplateColumns: `${LABEL_W}px repeat(${days.length}, minmax(${DAY_MIN}px, 1fr))`,
  };
  const minW = LABEL_W + days.length * DAY_MIN;

  const opts = selection.options;
  const keys = (["own", "part", "full"] as OptKey[]).filter((k) => opts[k]);
  const base = new Set(selection.base);
  const num = (id: string) => selection.orders[id]?.number ?? "";
  // Days the running (and already planned) orders still hold machines.
  const runDays = new Set(
    selection.running.flatMap((r) => days.filter((d) => d >= r.start && d <= r.finish)),
  );

  /** A bar clipped to the visible range; nothing if it is entirely outside. */
  const bar = (cls: string, a: string, b: string, text: string) => {
    if (!days.length || b < from || a > last) return null;
    const s = a < from ? from : a;
    const e = b > last ? last : b;
    return (
      <b
        title={`${text} · ${range(a, b)}`}
        className={cn(
          "z-[1] row-start-1 mx-0.5 flex h-[18px] items-center border px-[7px] text-[10.5px] font-medium whitespace-nowrap",
          a < from && b > last
            ? ""
            : a < from
              ? "rounded-r-[5px]"
              : b > last
                ? "rounded-l-[5px]"
                : "rounded-[5px]",
          cls,
        )}
        style={{ gridColumn: `${col(s)} / ${col(e) + 1}` }}
      >
        <span>{text}</span>
      </b>
    );
  };
  const row = (label: ReactNode, content: ReactNode, key: string, struck = false) => (
    <div
      key={key}
      className="relative grid min-h-7 items-center"
      style={{ ...grid, minWidth: minW }}
    >
      <span
        className={cn(
          "sticky left-0 z-[2] col-start-1 row-start-1 flex h-full items-center border-r border-line bg-white pr-3 pl-8 font-mono text-[11.5px] text-ink-3 group-data-[on=true]/opt:bg-surface-blue",
          struck && "text-subtle line-through",
        )}
      >
        {label}
      </span>
      {content}
    </div>
  );

  const groupTags = (k: OptKey): { tone: TagTone; text: string }[] => {
    const t: { tone: TagTone; text: string }[] = [];
    if (selection.using === k) t.push({ tone: "bl", text: "Current" });
    if (k === "part") t.push({ tone: "md", text: "Keeps your orders" });
    if (opts.best === k && k !== "own") t.push({ tone: "ok", text: "Best score" });
    return t;
  };
  const groupSub = (k: OptKey) => {
    const o = opts[k]!;
    const added = o.orders.filter((i) => !base.has(i)).length;
    const head =
      k === "part" && added
        ? `keeps your ${base.size} + ${added}`
        : plural(o.orders.length, "order");
    return `${head} · ${range(o.start, o.end)}`;
  };

  const invalid = from > to;
  const tooLong = daysBetween(from, to).length > MAX_DAYS;

  return (
    <details className="group overflow-hidden rounded-card border border-line" open>
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-5 py-4 select-none hover:bg-surface [&::-webkit-details-marker]:hidden">
        <h3 className="m-0 text-[17px] font-semibold">
          <span className="inline-block w-[18px] text-[13px] text-muted transition-transform group-open:rotate-90">
            ▸
          </span>
          Order timeline{" "}
          <small className="ml-1.5 text-[13px] font-normal text-muted">
            Running orders vs. the 3 selection options
          </small>
        </h3>
        <span className="hidden flex-wrap gap-4 text-[13px] text-ink-3 group-open:flex">
          <Legend cls="border-faint bg-surface-2" text="Running" />
          <Legend cls="border-load-ink/30 bg-load" text="Your order" />
          <Legend cls="border-ok-line bg-ok-bg" text="Added by optimizer" />
          <Legend cls="border-hi-line bg-hi-bg" text="Late" />
          <Legend
            cls="border-line bg-[repeating-linear-gradient(135deg,color-mix(in_srgb,var(--color-muted)_22%,transparent)_0_2px,transparent_2px_4px)]"
            text="Running orders' days"
          />
        </span>
      </summary>

      {/* date range */}
      <div className="flex flex-wrap items-center gap-3 border-t border-divider px-5 py-3 text-[13px] text-ink-2">
        <label className="flex items-center gap-2 rounded-full border border-line-input bg-white px-3.5 py-1.5 font-medium">
          From
          <input
            type="date"
            aria-label="Timeline from"
            value={from}
            max={to}
            onChange={(e) => e.target.value && setFrom(e.target.value)}
            className="border-0 bg-transparent text-[13px] text-ink-2"
          />
        </label>
        <label className="flex items-center gap-2 rounded-full border border-line-input bg-white px-3.5 py-1.5 font-medium">
          To
          <input
            type="date"
            aria-label="Timeline to"
            value={to}
            min={from}
            onChange={(e) => e.target.value && setTo(e.target.value)}
            className="border-0 bg-transparent text-[13px] text-ink-2"
          />
        </label>
        <button
          type="button"
          onClick={() => {
            setFrom(today);
            setTo(addDays(today, 20));
          }}
          className="cursor-pointer border-0 bg-transparent p-0 text-[13px] text-link"
        >
          Next 3 weeks
        </button>
        <span className="text-muted">{plural(days.length, "day")}</span>
        {(invalid || tooLong) && (
          <span role="alert" className="text-md">
            {invalid ? "'From' must be before 'To'." : `Showing the first ${MAX_DAYS} days.`}
          </span>
        )}
      </div>

      <div className="relative overflow-x-auto border-t border-divider">
        {/* day columns: Sundays, and days running orders hold the machines */}
        <div
          className="pointer-events-none absolute inset-0 grid"
          style={{ ...grid, minWidth: minW }}
        >
          <span />
          {days.map((d) => (
            <i
              key={d}
              className={cn(
                "border-l border-divider-2",
                dayParts(d).sun && "bg-surface",
                runDays.has(d) &&
                  "bg-[repeating-linear-gradient(135deg,color-mix(in_srgb,var(--color-muted)_9%,transparent)_0_4px,transparent_4px_9px)]",
              )}
            />
          ))}
        </div>
        <div
          className="relative grid min-h-11 items-center bg-surface text-center text-xs text-ink-2"
          style={{ ...grid, minWidth: minW }}
        >
          <span className="sticky left-0 z-[2] h-full border-r border-line bg-surface" />
          {days.map((d) => {
            const p = dayParts(d);
            return (
              <span key={d} className={cn("flex flex-col font-semibold", p.sun && "text-subtle")}>
                <small className="text-[10.5px] font-normal text-subtle">{p.dow}</small>
                {p.day}
              </span>
            );
          })}
        </div>

        {selection.running.length > 0 && (
          <div className="relative border-t border-line pb-1.5">
            <div className="flex items-center gap-2.5 px-5 pt-2.5 pb-1" style={{ minWidth: minW }}>
              <b className="text-sm">Running now</b>
              <small className="text-xs text-muted">in production or already planned</small>
              <Tag tone="lo" size="sm">
                Locked
              </Tag>
            </div>
            {selection.running.map((r) =>
              row(
                r.number,
                bar(
                  "border-faint bg-surface-2 text-ink-3",
                  r.start,
                  r.finish,
                  `${r.machine} · ${r.customer}`,
                ),
                r.id,
              ),
            )}
          </div>
        )}

        {keys.map((k) => {
          const o = opts[k]!;
          const on = focus === k;
          return (
            <div
              key={k}
              role="button"
              tabIndex={0}
              aria-pressed={on}
              aria-label={`Highlight ${OPT_LABEL[k]}`}
              onClick={() => onFocus(k)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onFocus(k)}
              data-on={on}
              className={cn(
                "group/opt relative cursor-pointer border-t border-line pb-1.5",
                on
                  ? "bg-primary/[0.04] shadow-[inset_3px_0_0_var(--color-primary)]"
                  : "hover:bg-ink/[0.015]",
              )}
            >
              <div
                className="flex flex-wrap items-center gap-2.5 px-5 pt-2.5 pb-1"
                style={{ minWidth: minW }}
              >
                <b className="text-sm">{OPT_LABEL[k]}</b>
                <small className="text-xs text-muted">{groupSub(k)}</small>
                {groupTags(k).map((t) => (
                  <Tag key={t.text} tone={t.tone} size="sm">
                    {t.text}
                  </Tag>
                ))}
              </div>
              {o.orders.map((id) => {
                const r = o.rows[id]!;
                const added = !base.has(id);
                const text = r.late_days
                  ? `${r.route[0] ?? ""} · ${plural(r.late_days, "day")} late`
                  : added && r.idle_fill
                    ? `${r.route[0] ?? ""} · idle machine`
                    : r.route.join(" → ");
                const cls = r.late_days
                  ? "border-hi-line bg-hi-bg text-hi"
                  : added
                    ? "border-ok-line bg-ok-bg text-ok"
                    : "border-load-ink/30 bg-load text-load-ink";
                return row(num(id), bar(cls, r.start, r.finish, text), id);
              })}
              {Object.entries(o.dropped).map(([id, why]) =>
                row(
                  num(id),
                  <span className="z-[1] col-[2/-1] row-start-1 pl-2 text-[11.5px] text-subtle italic">
                    Left out · {why}
                  </span>,
                  `x${id}`,
                  true,
                ),
              )}
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap justify-between gap-2 border-t border-divider px-5 py-3 text-[13px] text-muted">
        <span>{note(selection, keys)}</span>
        <span>Click an option in the table below to highlight it here.</span>
      </div>
    </details>
  );
}

/** The footer sentence, worked out from the numbers. */
function note(selection: Selection, keys: OptKey[]): string {
  const o = selection.options;
  const own = o.own;
  if (!own) return "Tick orders below to see them on the timeline.";
  const better = keys.filter((k) => k !== "own" && o[k] && o[k]!.idle_days < own.idle_days);
  if (better.length)
    return `Optimized options start more orders alongside the running ones, so machines sit idle for fewer days (${own.idle_days} → ${Math.min(...better.map((k) => o[k]!.idle_days))} machine-days).`;
  if (own.idle_days)
    return `${plural(own.idle_days, "machine-day")} idle while running orders finish (${own.idle_machines.join(", ")}).`;
  return "No machine sits idle while the running orders finish.";
}

function Legend({ cls, text }: { cls: string; text: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <i className={cn("inline-block size-3 rounded-[3px] border", cls)} />
      {text}
    </span>
  );
}
