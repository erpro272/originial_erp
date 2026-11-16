import { Fragment } from "react";
import { Link } from "react-router-dom";
import { KitIcon, type IconKind } from "@/components/kit/Kit";
import { Tag } from "@/components/ui/Tag";
import type { ContextCard } from "./api";
import { QUICK_PROMPTS } from "./prompts";

const ICON: Record<string, IconKind> = { machine: "gear", order: "wip", plan: "calendar" };

const QUICK_ACTIONS = [
  {
    label: "Analyse the current plan",
    hint: "Find risks and improvement opportunities",
    prompt: "Analyse the current plan",
  },
  {
    label: "Suggest fixes",
    hint: "Resolve delays, capacity or material issues",
    prompt: "Suggest fixes to improve the plan's contribution",
  },
  {
    label: "Run what-if scenario",
    hint: "e.g. add a night shift, change sequencing",
    prompt: "What if we add a night shift on CNC 01?",
  },
  {
    label: "Generate production plan",
    hint: "Best order sequence for the working plan",
    prompt: "Suggest the best order sequence for the production plan",
  },
];

function Card({ c }: { c: ContextCard }) {
  return (
    <section
      aria-label={`${c.title} context`}
      className="flex flex-col gap-3 rounded-card border border-line bg-white p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <KitIcon kind={ICON[c.kind] ?? "info"} className="size-5 shrink-0 text-primary" />
          <div className="flex min-w-0 flex-col">
            <h3 className="m-0 truncate text-[15px] font-semibold text-ink">{c.title}</h3>
            {c.subtitle && <span className="text-[12px] text-muted">{c.subtitle}</span>}
          </div>
        </div>
        {c.badge && (
          <Tag tone={c.badge.tone} size="sm">
            {c.badge.label}
          </Tag>
        )}
      </div>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-[13px]">
        {c.items.map((it) => (
          <Fragment key={it.label}>
            <dt className="text-muted">{it.label}</dt>
            <dd className="m-0 text-right font-medium text-ink-2">
              {it.tone ? (
                <Tag tone={it.tone} size="sm">
                  {it.value}
                </Tag>
              ) : (
                it.value
              )}
            </dd>
          </Fragment>
        ))}
      </dl>
      {c.link && (
        <Link to={c.link.href} className="text-[13px] font-medium text-link">
          {c.link.label} ↗
        </Link>
      )}
    </section>
  );
}

/** Right column: ERP context cards for what the conversation is about, quick actions and quick prompts. */
export function ContextPanel({
  cards,
  onPrompt,
  onDraft,
  busy,
}: {
  cards: ContextCard[];
  onPrompt: (text: string) => void;
  onDraft: (text: string) => void;
  busy: boolean;
}) {
  return (
    <aside
      aria-label="ERP context"
      className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto border-l border-line bg-surface/60 p-5"
    >
      <div className="flex items-start gap-3">
        <KitIcon kind="wip" className="mt-0.5 size-5 text-ink-2" />
        <div className="flex flex-col">
          <h2 className="m-0 text-[16px] font-semibold text-ink">ERP Context</h2>
          <span className="text-[12px] text-muted">Relevant data for this conversation</span>
        </div>
      </div>
      {cards.length === 0 ? (
        <p className="m-0 rounded-card border border-dashed border-faint bg-white px-4 py-5 text-[13px] text-muted">
          Ask about an order, a machine or the plan: their details appear here.
        </p>
      ) : (
        cards.map((c) => <Card key={`${c.kind}:${c.key}`} c={c} />)
      )}
      <section
        aria-label="Quick actions"
        className="flex flex-col gap-1 rounded-card border border-line bg-white p-3"
      >
        <h3 className="m-0 px-1 pb-1 text-[14px] font-semibold text-ink">⚡ Actions</h3>
        {QUICK_ACTIONS.map((a) => (
          <button
            key={a.label}
            type="button"
            disabled={busy}
            onClick={() =>
              a.label === "Run what-if scenario" ? onDraft(a.prompt) : onPrompt(a.prompt)
            }
            className="flex cursor-pointer flex-col rounded-lg px-2 py-2 text-left hover:bg-bl-bg disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="text-[13px] font-semibold text-ink">{a.label}</span>
            <span className="text-[12px] text-muted">{a.hint}</span>
          </button>
        ))}
      </section>
      <section
        aria-label="Quick prompts"
        className="flex flex-col gap-1.5 rounded-card border border-line bg-white p-3"
      >
        <h3 className="m-0 px-1 pb-1 text-[14px] font-semibold text-ink">Quick prompts</h3>
        {QUICK_PROMPTS.map((q) => (
          <button
            key={q}
            type="button"
            disabled={busy}
            onClick={() => onPrompt(q)}
            className="cursor-pointer rounded-lg border border-line px-3 py-2 text-left text-[13px] text-ink-2 hover:border-faint hover:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
          >
            {q}
          </button>
        ))}
      </section>
    </aside>
  );
}
