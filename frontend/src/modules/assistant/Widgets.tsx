import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { KitIcon, type IconKind } from "@/components/kit/Kit";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import type { Badge, Related, Widget } from "./api";

function BadgeTag({ b }: { b?: Badge }) {
  return b ? (
    <Tag tone={b.tone} size="sm">
      {b.label}
    </Tag>
  ) : null;
}

function Table({ w }: { w: Extract<Widget, { type: "table" }> }) {
  return (
    <div className="flex flex-col gap-2">
      {(w.title || w.badge) && (
        <div className="flex items-center gap-2">
          {w.title && <h4 className="m-0 text-[14px] font-semibold text-ink">{w.title}</h4>}
          <BadgeTag b={w.badge} />
        </div>
      )}
      {w.rows.length === 0 ? (
        <p className="m-0 text-[13px] text-muted">{w.empty ?? "Nothing to show."}</p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-line">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="bg-surface text-left text-[12px] text-muted">
                {w.columns.map((c) => (
                  <th
                    key={c.key}
                    className={cn("px-3 py-2 font-medium", c.align === "right" && "text-right")}
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {w.rows.map((r, i) => (
                <tr key={i} className="border-t border-divider">
                  {w.columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        "px-3 py-2 text-ink-2",
                        c.align === "right" && "text-right whitespace-nowrap",
                      )}
                    >
                      {c.key === "status" && r.status ? (
                        <Tag tone={(r.status_tone as Badge["tone"]) ?? "bl"} size="sm">
                          {r.status}
                        </Tag>
                      ) : (
                        (r[c.key] ?? "—")
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Bars({ w }: { w: Extract<Widget, { type: "bar_chart" }> }) {
  const pct = w.unit === "%";
  const max = Math.max(pct ? 100 : 1, ...w.bars.map((b) => b.value));
  const fmt = (v: number) => (pct ? `${v}%` : v.toLocaleString("en-IN"));
  return (
    <figure className="m-0 flex flex-col gap-2 rounded-card border border-line p-3">
      <figcaption className="text-[13px] font-semibold text-ink">{w.title}</figcaption>
      <div className="flex h-36 items-end gap-3 border-b border-line px-1" aria-hidden="true">
        {w.bars.map((b, i) => (
          <div
            key={i}
            className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1"
          >
            <span className="text-[12px] font-semibold text-ink">{fmt(b.value)}</span>
            <span
              className={cn(
                "w-full max-w-14 rounded-t-md",
                b.tone === "hi" || (pct && b.value > 100)
                  ? "bg-hi/70"
                  : i === 0
                    ? "bg-primary"
                    : "bg-primary/45",
              )}
              style={{ height: `${Math.max(2, (Math.min(b.value, max) / max) * 100)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-3 px-1" aria-hidden="true">
        {w.bars.map((b, i) => (
          <span key={i} className="flex-1 truncate text-center text-[11px] text-muted">
            {b.label}
          </span>
        ))}
      </div>
      <table className="sr-only">
        <caption>{w.title}</caption>
        <tbody>
          {w.bars.map((b, i) => (
            <tr key={i}>
              <th>{b.label}</th>
              <td>{fmt(b.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function KeyValues({ w }: { w: Extract<Widget, { type: "key_values" }> }) {
  return (
    <div className="flex flex-col gap-2 rounded-card border border-line p-3">
      <div className="flex items-center gap-2">
        <h4 className="m-0 text-[13px] font-semibold text-ink">{w.title}</h4>
        <BadgeTag b={w.badge} />
      </div>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
        {w.items.map((it, i) => (
          <Fragment key={i}>
            <dt className="text-muted">{it.label}</dt>
            <dd className="m-0 text-right">
              {it.link ? (
                <Link to={it.link} className="font-medium text-link">
                  {it.value}
                </Link>
              ) : it.tone ? (
                <Tag tone={it.tone} size="sm">
                  {it.value}
                </Tag>
              ) : (
                <span className="text-ink-2">{it.value}</span>
              )}
            </dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
}

export function WidgetView({ w }: { w: Widget }): ReactNode {
  switch (w.type) {
    case "table":
      return <Table w={w} />;
    case "bar_chart":
      return <Bars w={w} />;
    case "key_values":
      return <KeyValues w={w} />;
    case "section": {
      const tables = w.children.filter((c) => c.type === "table");
      const side = w.children.filter((c) => c.type !== "table");
      return (
        <section className="flex flex-col gap-3 rounded-card border border-line bg-white p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "grid size-5 place-items-center rounded-full text-white",
                w.icon === "alert" ? "bg-md-accent" : "bg-ok",
              )}
              aria-hidden="true"
            >
              <KitIcon kind={w.icon === "alert" ? "alert" : "info"} className="size-3" />
            </span>
            <h3 className="m-0 text-[15px] font-semibold text-ink">{w.title}</h3>
            <BadgeTag b={w.badge} />
          </div>
          {w.text && <p className="m-0 text-[13px] text-ink-3">{w.text}</p>}
          {tables.map((c, i) => (
            <WidgetView key={`t${i}`} w={c} />
          ))}
          {side.length > 0 && (
            <div className={cn("grid gap-3", side.length > 1 && "md:grid-cols-2")}>
              {side.map((c, i) => (
                <WidgetView key={`s${i}`} w={c} />
              ))}
            </div>
          )}
        </section>
      );
    }
    default:
      return null; // unknown widget types are never mounted
  }
}

const CHIP_ICON: Record<string, IconKind> = {
  order: "info",
  machine: "gear",
  plan: "calendar",
  customer: "heart",
  po: "wip",
  inventory: "wip",
  billing: "trend",
  screen: "info",
};

export function RelatedChips({ items }: { items: Related[] }) {
  return (
    <div className="flex flex-col gap-2">
      <h4 className="m-0 text-[13px] font-semibold text-ink-2">Related records</h4>
      <div className="flex flex-wrap gap-2">
        {items.map((r) => (
          <Link
            key={`${r.kind}:${r.label}`}
            to={r.href}
            className="flex items-center gap-2 rounded-card border border-line bg-white px-3 py-1.5 text-[13px] text-ink-2 hover:border-faint hover:bg-surface"
          >
            <KitIcon kind={CHIP_ICON[r.kind] ?? "trend"} className="size-4 text-ink-3" />
            {r.kind === "screen" ? `Open ${r.label}` : r.label}
            {!["plan", "billing", "inventory", "screen"].includes(r.kind) && (
              <span className="text-muted">
                ({r.kind === "po" ? "PO" : r.kind[0]!.toUpperCase() + r.kind.slice(1)})
              </span>
            )}
            <span aria-hidden="true" className="text-muted">
              ↗
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
