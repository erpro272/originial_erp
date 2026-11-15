import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { count, shortDate } from "@/lib/format";
import { useGenerate, usePatchPlan, type Plan, type PlanPatch, type SeqRow } from "./api";
import { Flash } from "./Flash";
import { generatedLabel, groupReason, isoDay, plural } from "./format";

const RULES = [
  { value: "deadline", label: "Deadline" },
  { value: "value", label: "Highest value" },
  { value: "margin", label: "Margin" },
  { value: "priority", label: "Customer priority" },
  { value: "custom", label: "Custom" },
] as const;
type Rule = (typeof RULES)[number]["value"];

const COLS =
  "grid-cols-[22px_28px_minmax(230px,2.4fr)_minmax(170px,1.5fr)_96px_96px_96px_72px_118px_32px]";

/** What an edit did, with a way back (drag / apply suggestion). */
interface Change {
  label: string;
  before: Snapshot;
  after?: Snapshot;
  undo: PlanPatch;
}
interface Snapshot {
  late: number;
  days: number;
  bottlenecks: number;
}

function snapshot(p: Plan): Snapshot {
  const ov = p.result.sequence.overview;
  return { late: ov.late ?? 0, days: ov.days, bottlenecks: ov.bottlenecks };
}

/** Step 2: the order the selected orders will be made in, and whether that plan holds up. */
export function SequenceStep({ plan, go }: { plan: Plan; go: (step: string) => void }) {
  const { can } = useAuth();
  const edit = can("planning.write");
  const seq = plan.result.sequence;
  const orders = plan.result.selection.orders;
  const num = (id: string) => orders[id]?.number ?? id;
  const ov = seq.overview;
  const patch = usePatchPlan(plan.id);
  const generate = useGenerate(plan.id);
  const { toast } = useToast();
  const [change, setChange] = useState<Change | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = seq.rows.map((r) => r.id);
  const busy = patch.isPending || generate.isPending;
  const hint = seq.hint && !seq.hint.dismissed ? seq.hint : null;

  const run = async (body: PlanPatch): Promise<Plan | null> => {
    try {
      return (await patch.mutateAsync(body)).plan;
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't update the plan.",
        tone: "error",
      });
      return null;
    }
  };
  /** Apply now, then show what changed with Undo (the owner's choice for reordering). */
  const applyWithUndo = async (body: PlanPatch, label: string) => {
    const undo: PlanPatch =
      plan.rule === "custom" ? { sequence: ids } : { rule: plan.rule as Rule };
    const before = snapshot(plan);
    const next = await run(body);
    if (next) setChange({ label, before, after: snapshot(next), undo });
  };

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const next = arrayMove(ids, ids.indexOf(String(e.active.id)), ids.indexOf(String(e.over.id)));
    const lockedMoved = seq.rows.some((r) => r.locked && next.indexOf(r.id) !== ids.indexOf(r.id));
    if (lockedMoved) {
      toast({ title: "Locked orders keep their slot. Unlock it first to move it.", tone: "error" });
      return;
    }
    void applyWithUndo({ sequence: next }, `${num(String(e.active.id))} moved`);
  };

  return (
    <section className="flex flex-col gap-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">
            Proposed manufacturing sequence
          </h2>
          <p className="m-0 text-[15px] text-muted">
            The order your {plural(ov.orders, "order")} will be made in, and whether that plan holds
            up.
          </p>
        </div>
        <div className="flex items-center gap-3 text-[13px] text-muted">
          {plan.generated_at && <span>Generated {generatedLabel(plan.generated_at)}</span>}
          {edit && (
            <Button
              variant="pill"
              size="pill"
              disabled={busy}
              onClick={async () => {
                try {
                  await generate.mutateAsync();
                  toast({
                    title: "Plan recalculated with the latest orders, stock and factory data",
                    tone: "success",
                  });
                } catch (e) {
                  toast({
                    title: e instanceof ApiError ? e.message : "Couldn't recalculate.",
                    tone: "error",
                  });
                }
              }}
            >
              ↻ Recalculate
            </Button>
          )}
        </div>
      </div>

      {/* overview + feasibility */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <section className="flex flex-col gap-5 rounded-card border border-line p-[22px]">
          <h3 className="m-0 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
            Plan overview
          </h3>
          <div className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-3">
            <Stat value={ov.orders} label="Orders included" />
            <Stat
              raw={ov.days}
              value={
                <>
                  {ov.days} <span className="text-base font-medium text-muted">days</span>
                </>
              }
              label={ov.start && ov.end ? `${dayMonth(ov.start)} → ${dayMonth(ov.end)}` : "–"}
            />
            <Stat
              raw={ov.utilisation}
              value={`${ov.utilisation}%`}
              label="Capacity utilisation"
              bar={ov.utilisation}
              tone={ov.utilisation >= 90 ? "md" : undefined}
            />
            <Stat
              raw={ov.on_time}
              value={
                <>
                  {ov.on_time}{" "}
                  <span className="text-base font-medium text-muted">of {ov.orders}</span>
                </>
              }
              label="Ship on time"
            />
            <Stat
              value={ov.bottlenecks}
              label={ov.bottlenecks === 1 ? "Bottleneck" : "Bottlenecks"}
              tone={ov.bottlenecks ? "hi" : undefined}
            />
            <Stat value={ov.parallel} label="Parallel runs" />
          </div>
        </section>

        <section
          aria-label="Plan feasibility"
          className={cn(
            "flex flex-col gap-3 rounded-card border p-[22px]",
            seq.feasibility.ok ? "border-ok-line" : "border-md-line",
          )}
        >
          <div className="flex items-center justify-between gap-3">
            <h3 className="m-0 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
              Plan feasibility
            </h3>
            <Tag tone={seq.feasibility.ok ? "ok" : "md"}>
              {seq.feasibility.ok ? "Feasible" : "Needs adjustment"}
            </Tag>
          </div>
          {seq.feasibility.lines.length === 0 ? (
            <p className="m-0 border-t border-divider pt-3 text-sm text-ink-2">
              Every order ships on time, with no machine, labour or material bottleneck.
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col p-0 text-sm">
              {seq.feasibility.lines.map((l) => (
                <li
                  key={l.text}
                  className="flex items-center justify-between gap-3 border-t border-divider py-3"
                >
                  <span className="flex items-center gap-2.5">
                    <span
                      aria-hidden
                      className={cn(
                        "size-2 flex-none rounded-full",
                        l.tone === "bad" ? "bg-hi" : "bg-md",
                      )}
                    />
                    <Flash value={l.text} />
                  </span>
                  {l.kind === "late" && hint && (
                    <a href="#hint" className="text-[13px] whitespace-nowrap no-underline">
                      See hint ↓
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
          {!seq.feasibility.ok && (
            <span className="text-xs text-subtle">
              {hint
                ? "Ordering fixes are shown below."
                : "No single reorder fixes this. Night shifts and express material come in Financial analysis."}
            </span>
          )}
        </section>
      </div>

      {/* suggested order */}
      {hint && (
        <section
          id="hint"
          aria-label="Suggested sequence"
          className="flex flex-wrap items-center justify-between gap-5 rounded-card border border-bl-line bg-surface-blue px-[22px] py-5"
        >
          <div className="flex items-start gap-3.5">
            <span
              aria-hidden
              className="grid size-9 flex-none place-items-center rounded-full bg-primary text-white"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M7 4v16" />
                <path d="M3 8l4-4 4 4" />
                <path d="M17 20V4" />
                <path d="M21 16l-4 4-4-4" />
              </svg>
            </span>
            <div className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <b className="text-base">{hint.title}</b>
                <Tag tone="bl" size="sm">
                  Suggested sequence
                </Tag>
              </span>
              <span className="text-sm text-ink-2">{hint.text}</span>
            </div>
          </div>
          {edit && (
            <div className="flex gap-2">
              <Button
                variant="pill"
                size="pill"
                disabled={busy}
                onClick={() => run({ dismiss_hint: true })}
              >
                Dismiss
              </Button>
              <Button
                size="sm"
                disabled={busy}
                onClick={() => applyWithUndo({ apply_hint: true }, hint.title)}
              >
                Apply this order
              </Button>
            </div>
          )}
        </section>
      )}

      {change && (
        <ChangeBanner
          change={change}
          busy={busy}
          onUndo={async () => {
            const c = change;
            setChange(null);
            if (await run(c.undo)) toast({ title: "Change undone", tone: "success" });
          }}
          onClose={() => setChange(null)}
        />
      )}

      {/* sequence list */}
      <section
        aria-label="Order sequence"
        className="overflow-hidden rounded-card border border-line"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <h3 className="m-0 text-[17px] font-semibold">Order sequence</h3>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[13px] text-muted">Sequenced by</span>
            <SegmentedControl<Rule>
              label="Sequenced by"
              size="sm"
              options={RULES.map((r) => ({ ...r }))}
              value={seq.rule as Rule}
              onChange={(v) => {
                if (!edit || busy || v === seq.rule) return;
                setChange(null);
                void run({ rule: v });
              }}
            />
            <label className="relative flex items-center gap-1.5 rounded-full border border-line-input px-3.5 py-1.5 text-[13px] font-medium text-ink-2 hover:border-faint">
              Start: {shortDate(seq.start)} <span aria-hidden>▾</span>
              <input
                type="date"
                aria-label="Plan start date"
                value={seq.start}
                min={isoDay(new Date())}
                disabled={!edit || busy}
                onClick={(e) => {
                  try {
                    e.currentTarget.showPicker();
                  } catch {
                    /* older browsers open it on focus */
                  }
                }}
                onChange={(e) => {
                  if (e.target.value && e.target.value !== seq.start) {
                    setChange(null);
                    void run({ start_date: e.target.value });
                  }
                }}
                className="absolute inset-0 cursor-pointer opacity-0"
              />
            </label>
          </div>
        </div>
        <div className="overflow-x-auto">
          <div className="min-w-[1060px]">
            <div
              className={cn(
                "grid items-center gap-3 border-t border-divider bg-surface px-5 py-3 text-xs font-semibold tracking-[0.04em] text-muted uppercase",
                COLS,
              )}
            >
              <span />
              <span>#</span>
              <span>Order</span>
              <span>Route</span>
              <span>Start</span>
              <span>Finish</span>
              <span>Deadline</span>
              <span className="text-right">Buffer</span>
              <span>Delivery</span>
              <span />
            </div>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                {seq.groups.map((g, gi) => {
                  const many = g.orders.length > 1;
                  return (
                    <div
                      key={g.orders.join()}
                      className={cn(
                        many && "border-l-[3px]",
                        gi % 2 ? "border-bl-line" : "border-primary",
                      )}
                    >
                      {many && (
                        <span className="flex items-center gap-1.5 border-t border-divider bg-white pt-3 pr-5 pl-[86px] text-xs font-semibold text-bl">
                          ∥ Run in parallel
                          <em
                            className={cn(
                              "font-medium not-italic",
                              g.conflict.length ? "text-hi" : "text-muted",
                            )}
                          >
                            · {groupReason(g, seq.rows)}
                          </em>
                        </span>
                      )}
                      {g.orders.map((id) => {
                        const r = seq.rows.find((x) => x.id === id);
                        return r ? (
                          <SeqLine
                            key={id}
                            row={r}
                            grouped={many}
                            plan={plan}
                            editable={edit && !busy}
                            onLock={(on) => run({ lock: { [id]: on } })}
                          />
                        ) : null;
                      })}
                    </div>
                  );
                })}
              </SortableContext>
            </DndContext>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface px-5 py-3 text-[13px] text-muted">
          <span className="flex flex-wrap items-center gap-5">
            <span>⋮⋮ Drag to reorder</span>
            <span>🔒 Locked orders keep their slot on recalculate</span>
            {seq.rows.some((r) => r.warn_machines.length) && (
              <span className="flex items-center gap-1.5">
                <MachineChip
                  name={seq.rows.find((r) => r.warn_machines.length)!.warn_machines[0]!}
                  warn
                />
                Overloaded machine
              </span>
            )}
          </span>
          <span className="text-subtle" title="Production schedule is being rebuilt">
            Day-by-day view in Production schedule · coming next
          </span>
        </div>
      </section>

      <div className="flex flex-wrap justify-between gap-3">
        <Button variant="pill" onClick={() => go("1")}>
          ← Selected orders
        </Button>
        <Button variant="dark" disabled title="Production schedule is being rebuilt">
          Next: Production schedule → <span className="font-normal">(coming next)</span>
        </Button>
      </div>
    </section>
  );
}

function dayMonth(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function ChangeBanner({
  change,
  busy,
  onUndo,
  onClose,
}: {
  change: Change;
  busy: boolean;
  onUndo: () => void;
  onClose: () => void;
}) {
  const { before: b, after: a } = change;
  const bits: string[] = [];
  if (a) {
    if (a.late !== b.late) bits.push(`Late deliveries ${b.late} → ${a.late}`);
    if (a.days !== b.days) bits.push(`Plan ${b.days} → ${a.days} days`);
    if (a.bottlenecks !== b.bottlenecks)
      bits.push(`Bottlenecks ${b.bottlenecks} → ${a.bottlenecks}`);
  }
  const worse = !!a && (a.late > b.late || a.days > b.days || a.bottlenecks > b.bottlenecks);
  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-card border px-5 py-3.5 text-sm",
        worse ? "border-hi-line bg-hi-wash" : "border-ok-line bg-ok-bg",
      )}
    >
      <span>
        <b>{change.label}.</b>{" "}
        {bits.length ? bits.join(" · ") : "No change to deliveries, plan length or bottlenecks."}
      </span>
      <span className="flex gap-2">
        <Button variant="pill" size="pill" disabled={busy} onClick={onUndo}>
          Undo
        </Button>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="cursor-pointer border-0 bg-transparent px-1 text-muted"
        >
          ×
        </button>
      </span>
    </div>
  );
}

function Stat({
  value,
  raw,
  label,
  tone,
  bar,
}: {
  value: ReactNode;
  raw?: number;
  label: string;
  tone?: "hi" | "md";
  bar?: number;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span
        className={cn(
          "text-[28px] leading-tight font-bold",
          tone === "hi" && "text-hi",
          tone === "md" && "text-md",
        )}
      >
        <Flash value={raw ?? value}>{value}</Flash>
      </span>
      {bar !== undefined && (
        <span className="block h-1.5 w-full max-w-[230px] overflow-hidden rounded-full bg-divider">
          <span
            className={cn("block h-full rounded-full", tone === "md" ? "bg-md" : "bg-primary")}
            style={{ width: `${Math.min(bar, 100)}%` }}
          />
        </span>
      )}
      <span className="text-[13px] text-muted">{label}</span>
    </div>
  );
}

function MachineChip({ name, warn }: { name: string; warn?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-md border px-1.5 py-0.5 font-mono text-xs",
        warn ? "border-hi-line bg-hi-bg text-hi" : "border-line bg-surface-2 text-ink-2",
      )}
    >
      {name}
    </span>
  );
}

function SeqLine({
  row,
  grouped,
  plan,
  editable,
  onLock,
}: {
  row: SeqRow;
  grouped: boolean;
  plan: Plan;
  editable: boolean;
  onLock: (on: boolean) => void;
}) {
  const o = plan.result.selection.orders[row.id]!;
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: row.id, disabled: !editable || row.locked });
  const late = row.late_days > 0;
  return (
    <div
      ref={setNodeRef}
      data-testid={`seq-${o.number}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "grid items-center gap-3 border-t border-divider bg-white px-5 py-3.5 text-sm",
        COLS,
        grouped && "border-dashed",
        late && "bg-hi-wash",
        isDragging && "relative z-10 opacity-80 shadow-tip",
      )}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Drag to reorder ${o.number}`}
        className={cn(
          "border-0 bg-transparent p-0 text-sm tracking-[-2px] text-faint",
          editable && !row.locked
            ? "cursor-grab hover:text-muted"
            : "cursor-not-allowed opacity-40",
        )}
      >
        ⋮⋮
      </button>
      <span className="grid size-6 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-ink-2">
        {row.rank}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <b className="font-mono text-[15px] font-semibold">{o.number}</b>
        <small className="truncate text-[13px] text-muted">
          {o.customer} · {o.product} · {count(o.qty)} {o.unit}
        </small>
      </span>
      <span
        className="flex flex-wrap items-center gap-1.5"
        aria-label={`Route ${row.machines.join(" then ")}`}
      >
        {row.machines.map((m, i) => (
          <span key={`${m}${i}`} className="flex items-center gap-1.5">
            {i > 0 && <i className="text-subtle not-italic">→</i>}
            <MachineChip name={m} warn={row.warn_machines.includes(m)} />
          </span>
        ))}
      </span>
      <span>
        <Flash value={row.start}>{shortDate(row.start)}</Flash>
      </span>
      <span className={cn(late && "font-semibold text-hi")}>
        <Flash value={row.finish}>{shortDate(row.finish)}</Flash>
      </span>
      <span>{shortDate(row.deadline)}</span>
      <span className={cn("text-right", late && "text-hi")}>
        <Flash value={row.buffer}>
          {row.buffer < 0 ? `−${plural(-row.buffer, "day")}` : plural(row.buffer, "day")}
        </Flash>
      </span>
      <span>
        {late ? (
          <Tag tone="hi">Late · {plural(row.late_days, "day")}</Tag>
        ) : row.status === "material" ? (
          <Tag tone="md">Material short</Tag>
        ) : (
          <Tag tone="ok">On time</Tag>
        )}
      </span>
      <button
        type="button"
        disabled={!editable}
        title={row.locked ? "Locked: keeps its slot when recalculated" : "Unlocked"}
        aria-label={`${row.locked ? "Unlock" : "Lock"} ${o.number}`}
        aria-pressed={row.locked}
        onClick={() => onLock(!row.locked)}
        className={cn(
          "cursor-pointer border-0 bg-transparent p-0 text-center text-sm",
          row.locked ? "opacity-100" : "opacity-35 hover:opacity-70",
        )}
      >
        {row.locked ? "🔒" : "🔓"}
      </button>
    </div>
  );
}
