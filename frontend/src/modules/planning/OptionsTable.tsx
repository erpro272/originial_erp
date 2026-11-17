import { AssistantBadge } from "@/components/ui/AssistantBadge";
import { Button } from "@/components/ui/Button";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { rupeesCompact } from "@/lib/format";
import { OPT_LABEL, type OptKey, type Selection, type SelectionOption } from "./api";
import { plural, range } from "./format";

interface Metric {
  label: string;
  get: (o: SelectionOption) => number;
  show: (o: SelectionOption) => string;
  best: "min" | "max";
  key?: boolean;
}

const SUB: Record<OptKey, string> = {
  own: "Only the orders you picked",
  part: "Keeps all your orders, adds what fits",
  full: "Best mix from all accepted orders",
};

/** "Order selection options": your selection vs. what the optimizer suggests (numbers only). */
export function OptionsTable({
  selection,
  focus,
  onFocus,
  onUse,
  editable,
  busy,
}: {
  selection: Selection;
  focus: OptKey;
  onFocus: (k: OptKey) => void;
  onUse: (k: OptKey) => void;
  editable: boolean;
  busy: boolean;
}) {
  const opts = selection.options;
  const keys: OptKey[] = ["own", "part", "full"];
  const base = new Set(selection.base);
  const short = (id: string) => (selection.orders[id]?.number ?? "").replace(/^ORD-/, "");
  const late = (o: SelectionOption) => o.late.map((i) => selection.orders[i]?.number).join(", ");
  const metrics: Metric[] = [
    { label: "Sales value", get: (o) => o.value, show: (o) => rupeesCompact(o.value), best: "max" },
    {
      label: "Production window",
      get: (o) => o.days,
      show: (o) => `${range(o.start, o.end)} · ${plural(o.days, "day")}`,
      best: "min",
    },
    {
      label: "Orders starting alongside running orders",
      get: (o) => o.alongside,
      show: (o) => String(o.alongside),
      best: "max",
    },
    {
      label: "Idle machine-days while running orders run",
      get: (o) => o.idle_days,
      show: (o) => (o.idle_days ? `${o.idle_days} · ${o.idle_machines.join(", ")}` : "0"),
      best: "min",
    },
    {
      label: "Machine utilisation",
      get: (o) => o.utilisation,
      show: (o) => `${o.utilisation}%`,
      best: "max",
    },
    {
      label: "Bottlenecks",
      get: (o) => o.bottlenecks,
      show: (o) =>
        o.bottlenecks ? `${o.bottlenecks} · ${o.bottleneck_names.join(", ").toLowerCase()}` : "0",
      best: "min",
    },
    {
      label: "Late deliveries",
      get: (o) => o.late.length,
      show: (o) => (o.late.length ? `${o.late.length} · ${late(o)}` : "0"),
      best: "min",
    },
    {
      label: "Contribution",
      get: (o) => o.contribution,
      show: (o) => rupeesCompact(o.contribution),
      best: "max",
    },
    {
      label: "Contribution margin",
      get: (o) => o.margin,
      show: (o) => `${o.margin}%`,
      best: "max",
    },
    {
      label: "Contribution per production day",
      get: (o) => o.per_day,
      show: (o) => rupeesCompact(o.per_day),
      best: "max",
      key: true,
    },
  ];
  const present = keys.filter((k) => opts[k]);
  const bestOf = (m: Metric) => {
    const vals = present.map((k) => m.get(opts[k]!));
    const b = m.best === "max" ? Math.max(...vals) : Math.min(...vals);
    return new Set(present.filter((k) => m.get(opts[k]!) === b && vals.some((v) => v !== b)));
  };
  const inUse = (k: OptKey) => selection.using === k;

  // Plain-language summary from the numbers above (the code does the maths, not an AI).
  const summary = (() => {
    const o = opts.own,
      p = opts.part,
      f = opts.full;
    if (!o || !f) return null;
    const out: string[] = [];
    const diff = f.contribution - o.contribution;
    const dropped = Object.keys(f.dropped).map((i) => selection.orders[i]?.number);
    let s = `Fully optimized earns ${rupeesCompact(Math.abs(diff))} ${diff >= 0 ? "more" : "less"} than your selection`;
    if (f.late.length < o.late.length)
      s += f.late.length ? ", with fewer late deliveries" : ", with no late deliveries";
    if (dropped.length) s += `, but leaves out ${dropped.join(", ")}`;
    out.push(s + ".");
    if (p && p.orders.length > o.orders.length) {
      const pd = p.contribution - o.contribution;
      out.push(
        `Partly optimized keeps all your orders, adds ${p.orders.length - o.orders.length} and earns ${rupeesCompact(Math.abs(pd))} ${pd >= 0 ? "more" : "less"}` +
          (p.late.length ? `; ${plural(p.late.length, "order")} still ships late.` : "."),
      );
    }
    return out.join(" ");
  })();

  return (
    <section className="overflow-hidden rounded-card border border-line">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <h3 className="m-0 text-[17px] font-semibold">
          Order selection options{" "}
          <small className="ml-1.5 text-[13px] font-normal text-muted">
            Your selection vs. what the optimizer suggests
          </small>
        </h3>
        <AssistantBadge>Planning assistant</AssistantBadge>
      </div>
      {present.length === 0 ? (
        <p className="m-0 border-t border-divider px-5 py-8 text-center text-sm text-muted">
          Tick at least one order to compare options.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse">
            <thead>
              <tr>
                <th className="w-[240px]" />
                {keys.map((k) => (
                  <th
                    key={k}
                    scope="col"
                    tabIndex={0}
                    aria-pressed={focus === k}
                    onClick={() => onFocus(k)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onFocus(k)}
                    className={cn(
                      "cursor-pointer p-4 text-left align-top font-normal normal-case hover:bg-surface",
                      focus === k &&
                        "bg-surface-blue shadow-[inset_0_3px_0_var(--color-primary)] hover:bg-surface-blue",
                    )}
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <b className="text-[17px] font-semibold">{OPT_LABEL[k]}</b>
                      {inUse(k) && (
                        <Tag tone="bl" size="sm">
                          Current
                        </Tag>
                      )}
                      {opts.best === k && k !== "own" && (
                        <Tag tone="ok" size="sm">
                          Best score
                        </Tag>
                      )}
                    </div>
                    <small className="text-[13px] text-muted">{SUB[k]}</small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th
                  scope="row"
                  className="border-t border-divider px-5 py-3 text-left text-[13px] font-medium text-muted"
                >
                  Orders
                </th>
                {keys.map((k) => (
                  <td key={k} className="border-t border-divider px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {opts[k]?.orders.map((id) => (
                        <span
                          key={id}
                          className={cn(
                            "rounded-md border px-1.5 py-0.5 font-mono text-[11.5px]",
                            base.has(id)
                              ? "border-line-input bg-surface-2 text-ink-2"
                              : "border-ok-line bg-ok-bg text-ok",
                          )}
                        >
                          {base.has(id) ? "" : "+"}
                          {short(id)}
                        </span>
                      ))}
                      {Object.keys(opts[k]?.dropped ?? {}).map((id) => (
                        <span
                          key={id}
                          className="rounded-md border border-line-input bg-card px-1.5 py-0.5 font-mono text-[11.5px] text-subtle line-through"
                        >
                          {short(id)}
                        </span>
                      ))}
                    </div>
                  </td>
                ))}
              </tr>
              {metrics.map((m) => {
                const best = bestOf(m);
                return (
                  <tr key={m.label}>
                    <th
                      scope="row"
                      className={cn(
                        "border-t border-divider px-5 py-3 text-left text-[13px] font-medium whitespace-nowrap text-muted",
                        m.key && "text-[15px] font-semibold text-ink",
                      )}
                    >
                      {m.label}
                    </th>
                    {keys.map((k) => (
                      <td
                        key={k}
                        className={cn(
                          "border-t border-divider px-4 py-3 text-sm",
                          m.key && "text-[15px]",
                        )}
                      >
                        {opts[k] ? (
                          <span
                            className={cn(
                              best.has(k) &&
                                "-ml-2 rounded-md bg-ok-bg px-2 py-0.5 font-semibold text-ok",
                            )}
                          >
                            {m.show(opts[k]!)}
                          </span>
                        ) : (
                          "–"
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
              <tr>
                <th />
                {keys.map((k) => (
                  <td key={k} className="border-t border-line px-4 py-4">
                    {inUse(k) ? (
                      <Button variant="pill" size="pill" disabled>
                        ✓ Using this
                      </Button>
                    ) : (
                      editable &&
                      opts[k] && (
                        <Button variant="dark" size="sm" disabled={busy} onClick={() => onUse(k)}>
                          Use this selection
                        </Button>
                      )
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {summary && (
        <div className="border-t border-divider px-5 py-3.5 text-sm text-ink-2">{summary}</div>
      )}
      <div className="flex flex-wrap gap-4 border-t border-divider px-5 py-3 text-[13px] text-muted">
        <span>
          <span className="mr-1 inline-block size-2.5 rounded-[3px] border border-ok-line bg-ok-bg align-[-1px]" />{" "}
          Best in row
        </span>
        <span>
          Best score: no late deliveries where possible, then the most contribution per production
          day, then filling machines left idle by running orders.
        </span>
      </div>
    </section>
  );
}
