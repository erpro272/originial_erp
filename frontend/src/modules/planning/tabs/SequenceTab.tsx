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
import { useState } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { count, dateTime, shortDate } from "@/lib/format";
import { usePatchPlan, usePlan, type SeqRow } from "../api";
import { Flash } from "../bits";
import { plural, range } from "../format";
import type { TabProps } from "../PlanningPage";
import { useReorder } from "../reorder";

const RULES = [
  { value: "deadline", label: "Deadline" },
  { value: "value", label: "Highest value" },
  { value: "margin", label: "Margin" },
  { value: "priority", label: "Customer priority" },
  { value: "custom", label: "Custom" },
] as const;
type Rule = (typeof RULES)[number]["value"];

const COLS =
  "grid-cols-[28px_28px_minmax(220px,2.2fr)_minmax(170px,1.4fr)_100px_100px_100px_70px_120px_36px]";

export function SequenceTab({ plan, go }: TabProps) {
  const { can } = useAuth();
  const edit = can("planning.write");
  const seq = plan.result.sequence;
  const o = plan.result.selection.orders;
  const patch = usePatchPlan(plan.id);
  const refetch = usePlan().refetch;
  const reorder = useReorder(plan);
  const { toast } = useToast();
  const [hideHint, setHideHint] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = seq.rows.map((r) => r.id);
  const ov = seq.overview;

  const run = async (body: Parameters<typeof patch.mutateAsync>[0]) => {
    try {
      await patch.mutateAsync(body);
    } catch (e) {
      toast({
        title: e instanceof ApiError ? e.message : "Couldn't update the plan.",
        tone: "error",
      });
    }
  };
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const next = arrayMove(ids, ids.indexOf(String(e.active.id)), ids.indexOf(String(e.over.id)));
    void reorder.request({ sequence: next }, o[String(e.active.id)]?.number ?? "");
  };

  return (
    <section className="flex flex-col gap-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">
            Proposed manufacturing sequence
          </h2>
          <p className="m-0 text-sm text-muted">
            The order your {plural(ov.orders, "order")} will be made in, and whether that plan holds
            up.
          </p>
        </div>
        <div className="flex items-center gap-3 text-[13px] text-muted">
          {plan.generated_at && <span>Generated {dateTime(plan.generated_at)}</span>}
          <Button variant="pill" size="pill" onClick={() => void refetch()}>
            ↻ Recalculate
          </Button>
        </div>
      </div>

      {/* overview + feasibility */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section className="flex flex-col gap-4 rounded-card border border-line p-[22px]">
          <h3 className="m-0 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
            Plan overview
          </h3>
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-3">
            <Stat value={ov.orders} label="Orders included" />
            <Stat
              value={
                <>
                  {ov.days} <span className="text-base font-medium text-muted">days</span>
                </>
              }
              raw={ov.days}
              label={range(ov.start, ov.end).replace("–", " → ")}
            />
            <Stat
              value={`${ov.utilisation}%`}
              raw={ov.utilisation}
              label="Capacity utilisation"
              bar={ov.utilisation}
            />
            <Stat
              value={
                <>
                  {ov.on_time}{" "}
                  <span className="text-base font-medium text-muted">of {ov.orders}</span>
                </>
              }
              raw={ov.on_time}
              label="Ship on time"
              tone={ov.on_time < ov.orders ? "hi" : undefined}
            />
            <Stat
              value={ov.bottlenecks}
              label="Bottlenecks"
              tone={ov.bottlenecks ? "hi" : undefined}
            />
            <Stat value={ov.parallel} label="Parallel runs" />
          </div>
        </section>
        <section
          className={cn(
            "flex flex-col gap-3.5 rounded-card border p-[22px]",
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
            <p className="m-0 text-sm text-ink-2">Every order ships on time with no bottlenecks.</p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
              {seq.feasibility.lines.map((l) => (
                <li key={l} className="flex items-start gap-2.5">
                  <span className="mt-1.5 size-2 flex-none rounded-full bg-hi" />
                  <Flash value={l} />
                </li>
              ))}
            </ul>
          )}
          {!seq.feasibility.ok && (
            <span className="text-[13px] text-muted">
              {seq.hint ? (
                <a href="#hint">See the suggested order ↓</a>
              ) : (
                "Fixes are in Financial analysis."
              )}
            </span>
          )}
        </section>
      </div>

      {/* hint */}
      {seq.hint && hideHint !== seq.hint.title && (
        <section
          id="hint"
          className="flex flex-wrap items-center justify-between gap-5 rounded-card border border-bl-line bg-surface-blue px-[22px] py-5"
        >
          <div className="flex items-start gap-3.5">
            <span
              aria-hidden
              className="grid size-9 flex-none place-items-center rounded-full bg-white text-bl"
            >
              ⇅
            </span>
            <div className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <b className="text-[15px]">{seq.hint.title}</b>
                <Tag tone="bl" size="sm">
                  Suggested sequence
                </Tag>
              </span>
              <span className="text-sm text-ink-2">{seq.hint.text}</span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="pill" size="pill" onClick={() => setHideHint(seq.hint!.title)}>
              Dismiss
            </Button>
            {edit && (
              <Button
                size="sm"
                disabled={patch.isPending}
                onClick={() => run({ apply_hint: true })}
              >
                Apply this order
              </Button>
            )}
          </div>
        </section>
      )}

      {/* sequence list */}
      <section className="overflow-hidden rounded-card border border-line">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <h3 className="m-0 text-[17px] font-semibold">Order sequence</h3>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[13px] text-muted">Sequenced by</span>
            <SegmentedControl<Rule>
              label="Sequencing rule"
              size="sm"
              options={RULES.map((r) => ({ ...r }))}
              value={seq.rule as Rule}
              onChange={(v) => edit && v !== "custom" && run({ rule: v })}
            />
            <label className="flex items-center gap-2 rounded-full border border-line-input px-3.5 py-1.5 text-[13px] font-medium text-ink-2">
              Start
              <input
                type="date"
                value={seq.start}
                disabled={!edit}
                onChange={(e) => e.target.value && run({ start_date: e.target.value })}
                className="border-0 bg-transparent text-[13px] text-ink-2"
              />
            </label>
          </div>
        </div>
        <div className="overflow-x-auto">
          <div className="min-w-[1080px]">
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
                {seq.groups.map((g, gi) => (
                  <div
                    key={g.orders.join()}
                    className={cn(
                      g.orders.length > 1 && "relative -mt-px border-l-[3px]",
                      gi % 2 ? "border-bl-line" : "border-primary",
                    )}
                  >
                    {g.orders.length > 1 && (
                      <span className="flex items-center gap-2 border-t border-divider bg-white pt-2.5 pr-5 pl-[88px] text-xs font-semibold text-bl">
                        ∥ Run in parallel
                        <em className="font-medium text-muted not-italic">
                          {g.shared.length
                            ? `· both need ${g.shared.join(", ")}`
                            : "· different lines, same days"}
                        </em>
                      </span>
                    )}
                    {g.orders.map((id, i) => {
                      const r = seq.rows.find((x) => x.id === id);
                      return r ? (
                        <SeqLine
                          key={id}
                          row={r}
                          grouped={g.orders.length > 1 && i > 0}
                          plan={plan}
                          editable={edit}
                          onLock={(on) => run({ lock: { [id]: on } })}
                        />
                      ) : null;
                    })}
                  </div>
                ))}
              </SortableContext>
            </DndContext>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface px-5 py-3 text-[13px] text-muted">
          <span className="flex flex-wrap gap-4">
            <span>⋮⋮ Drag to reorder</span>
            <span>🔒 Locked orders keep their slot on recalculate</span>
            <span>
              <span className="rounded-md border border-hi-line bg-hi-bg px-1.5 py-0.5 font-mono text-xs text-hi">
                Machine
              </span>{" "}
              Overloaded machine
            </span>
          </span>
          <button
            type="button"
            className="cursor-pointer border-0 bg-transparent text-[13px] text-link"
            onClick={() => go(3)}
          >
            Day-by-day view in Production schedule →
          </button>
        </div>
      </section>

      <div className="flex justify-between">
        <Button variant="pill" onClick={() => go(1)}>
          ← Selected orders
        </Button>
        <Button variant="dark" onClick={() => go(3)}>
          Next: Production schedule →
        </Button>
      </div>
      {reorder.modal}
    </section>
  );
}

function Stat({
  value,
  raw,
  label,
  tone,
  bar,
}: {
  value: React.ReactNode;
  raw?: number;
  label: string;
  tone?: "hi";
  bar?: number;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className={cn("text-[28px] leading-tight font-bold", tone === "hi" && "text-hi")}>
        <Flash value={raw ?? value}>{value}</Flash>
      </span>
      {bar !== undefined && (
        <span className="block h-1.5 w-28 overflow-hidden rounded-full bg-divider">
          <span
            className="block h-full rounded-full bg-primary"
            style={{ width: `${Math.min(bar, 100)}%` }}
          />
        </span>
      )}
      <span className="text-[13px] text-muted">{label}</span>
    </div>
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
  plan: TabProps["plan"];
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
  } = useSortable({
    id: row.id,
    disabled: !editable || row.locked,
  });
  const late = row.late_days > 0;
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "grid items-center gap-3 border-t border-divider bg-white px-5 py-3.5 text-sm",
        COLS,
        grouped && "border-dashed border-line-input",
        late && "bg-hi-wash",
        isDragging && "shadow-pop relative z-10 opacity-80",
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
        <b className="font-mono text-sm font-semibold">{o.number}</b>
        <small className="truncate text-[13px] text-muted">
          {o.customer} · {o.product} · {count(o.qty)} {o.unit}
        </small>
      </span>
      <span className="flex flex-wrap items-center gap-1">
        {row.machines.map((m, i) => (
          <span key={`${m}${i}`} className="flex items-center gap-1">
            {i > 0 && <i className="text-subtle not-italic">→</i>}
            <span
              className={cn(
                "rounded-md border px-1.5 py-0.5 font-mono text-xs",
                row.warn_machines.includes(m)
                  ? "border-hi-line bg-hi-bg text-hi"
                  : "border-line-input bg-surface-2 text-ink-2",
              )}
            >
              {m}
            </span>
          </span>
        ))}
      </span>
      <span>
        <Flash value={row.start}>{shortDate(row.start)}</Flash>
      </span>
      <span>
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
          "cursor-pointer border-0 bg-transparent text-center text-sm",
          row.locked ? "opacity-100" : "opacity-35 hover:opacity-70",
        )}
      >
        {row.locked ? "🔒" : "🔓"}
      </button>
    </div>
  );
}
