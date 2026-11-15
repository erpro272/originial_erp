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
import { useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { TipRow, Tooltip } from "@/components/ui/Menu";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { count, rupeesCompact, shortDate } from "@/lib/format";
import {
  machineTone,
  usePatchPlan,
  useSaveSchedule,
  type GanttRow,
  type Plan,
  type PlanPatch,
} from "./api";
import { addDays, dayParts, daysBetween, generatedLabel, plural, range } from "./format";
import { useReorder } from "./reorder";

const LABEL_W = 280;
const DAY_W = 54;
const WINDOW = 18; // days shown, like the mockup (13 – 30 Nov)

const HATCH =
  "bg-[repeating-linear-gradient(135deg,color-mix(in_srgb,var(--color-hi)_14%,transparent)_0_4px,transparent_4px_9px)]";
const SETUP =
  "bg-[repeating-linear-gradient(135deg,var(--color-md-bg)_0_4px,color-mix(in_srgb,var(--color-md-accent)_22%,white)_4px_8px)]";

interface UndoItem {
  body: PlanPatch;
  label: string;
}

/** Step 3: which machine runs which order, day by day. */
export function ScheduleStep({ plan, go }: { plan: Plan; go: (step: string) => void }) {
  const { can } = useAuth();
  const edit = can("planning.write") && plan.status !== "approved";
  const sch = plan.result.schedule;
  const seq = plan.result.sequence;
  const orders = plan.result.selection.orders;
  const num = (id: string) => orders[id]?.number ?? id;
  const reorder = useReorder(plan);
  const patch = usePatchPlan(plan.id);
  const save = useSaveSchedule(plan.id);
  const { toast } = useToast();
  const [undo, setUndo] = useState<UndoItem[]>([]);
  const [from, setFrom] = useState(sch.today);
  const days = daysBetween(from, addDays(from, WINDOW - 1));
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const busy = reorder.busy || patch.isPending || save.isPending;

  // two grid columns per day: a route step that hands over mid-day takes half the day
  const grid: CSSProperties = {
    gridTemplateColumns: `${LABEL_W}px repeat(${days.length * 2}, minmax(${DAY_W / 2}px, 1fr))`,
  };
  const minW = LABEL_W + days.length * DAY_W;
  const machineOrder = sch.load.map((l) => l.machine);
  const used = new Set(sch.rows.flatMap((r) => r.steps.map((s) => s.machine)));
  const legend = sch.load.filter((l) => used.has(l.machine));
  const hot = new Set(sch.rows.flatMap((r) => r.over_days));
  const running = sch.rows.filter((r) => r.running);
  const planned = sch.rows.filter((r) => !r.running);
  const ids = planned.map((r) => r.id);
  const seqRow = Object.fromEntries(seq.rows.map((r) => [r.id, r]));
  const runInfo = Object.fromEntries(plan.result.selection.running.map((r) => [r.id, r]));
  // machine days a late order queued for (step 2 "over capacity"): ringed in the load grid
  const queued = new Set(
    sch.rows.flatMap((r) =>
      r.wait.flatMap((w) => daysBetween(w.from, w.to).map((d) => `${w.machine}|${d}`)),
    ),
  );

  const change = async (body: PlanPatch, label: string, inverse: PlanPatch, action?: string) => {
    if (await reorder.request(body, label, action))
      setUndo((u) => [...u.slice(-19), { body: inverse, label }]);
  };
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const next = arrayMove(ids, ids.indexOf(String(e.active.id)), ids.indexOf(String(e.over.id)));
    const inverse: PlanPatch =
      plan.rule === "custom" ? { sequence: ids } : { rule: plan.rule as "value" };
    void change({ sequence: next }, num(String(e.active.id)), inverse);
  };
  const onResize = (id: string, finish: string) => {
    void change(
      { pin: { [id]: finish } },
      num(id),
      { pin: { [id]: seqRow[id]?.pinned ?? null } },
      `Finishing ${num(id)} on ${shortDate(finish)}`,
    );
  };

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4 lg:flex-nowrap">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Production schedule</h2>
          <p className="m-0 text-[15px] text-muted">
            Which machine runs which order, day by day. Drag an order by ⋮⋮ to reorder it, or drag a
            bar's edge to change its dates.
          </p>
        </div>
        <div className="flex flex-none items-center gap-2">
          {edit && (
            <Button
              variant="pill"
              size="pill"
              disabled={!undo.length || busy}
              title={undo.length ? `Undo: ${undo[undo.length - 1]!.label}` : "Nothing to undo"}
              onClick={async () => {
                const last = undo[undo.length - 1]!;
                try {
                  await patch.mutateAsync(last.body);
                  setUndo((u) => u.slice(0, -1));
                  toast({ title: `Undone · ${last.label}`, tone: "success" });
                } catch (e) {
                  toast({
                    title: e instanceof ApiError ? e.message : "Couldn't undo.",
                    tone: "error",
                  });
                }
              }}
            >
              ↶ Undo
            </Button>
          )}
          <span className="flex items-center rounded-full border border-line-input text-[13px] font-medium text-ink-2">
            <button
              type="button"
              aria-label="Earlier week"
              onClick={() => setFrom(addDays(from, -7))}
              className="cursor-pointer border-0 bg-transparent py-2 pr-1 pl-3.5 text-ink-2"
            >
              ‹
            </button>
            <span className="px-1.5">
              {range(days[0], days[days.length - 1]).replace("–", " – ")}{" "}
              {days[days.length - 1]!.slice(0, 4)}
            </span>
            <button
              type="button"
              aria-label="Later week"
              onClick={() => setFrom(addDays(from, 7))}
              className="cursor-pointer border-0 bg-transparent py-2 pr-3.5 pl-1 text-ink-2"
            >
              ›
            </button>
          </span>
          {edit && (
            <Button
              variant="dark"
              disabled={busy}
              title={
                plan.schedule_saved_at
                  ? `Last saved ${generatedLabel(plan.schedule_saved_at)}`
                  : undefined
              }
              onClick={async () => {
                try {
                  await save.mutateAsync();
                  setUndo([]);
                  toast({ title: "Schedule saved", tone: "success" });
                } catch (e) {
                  toast({
                    title: e instanceof ApiError ? e.message : "Couldn't save.",
                    tone: "error",
                  });
                }
              }}
            >
              Save schedule
            </Button>
          )}
        </div>
      </div>

      {sch.chips.length > 0 && (
        <div className="flex flex-wrap gap-2.5" aria-label="Bottlenecks">
          {sch.chips.map((c) => (
            <div
              key={c.title}
              className={cn(
                "flex items-center gap-2.5 rounded-full border px-4 py-2 text-sm",
                c.tone === "bad" ? "border-hi-line bg-hi-wash" : "border-md-line bg-md-bg/40",
              )}
            >
              <span
                className={cn("size-2 rounded-full", c.tone === "bad" ? "bg-hi" : "bg-md-accent")}
              />
              <b>{c.title}</b>
              <span className="text-muted">{c.text}</span>
            </div>
          ))}
        </div>
      )}

      <section className="overflow-hidden rounded-card border border-line">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex flex-wrap gap-4 text-[13px] text-ink-3">
            {legend.map((l) => (
              <span key={l.machine} className="flex items-center gap-1.5">
                <i
                  className={cn(
                    "inline-block size-3 rounded-[3px] border bg-current!",
                    machineTone(l.machine, machineOrder),
                  )}
                />
                {l.name}
              </span>
            ))}
            <span className="flex items-center gap-1.5">
              <i className={cn("inline-block size-3 rounded-[3px] border border-md-line", SETUP)} />
              Setup / changeover
            </span>
            <span className="flex items-center gap-1.5">
              <i className="inline-block size-3 rounded-[3px] border border-line-input bg-surface-2" />
              In production
            </span>
            <span className="flex items-center gap-1.5">
              <i className={cn("inline-block size-3 rounded-[3px] border-2 border-hi", HATCH)} />
              Bottleneck
            </span>
            <span className="flex items-center gap-1.5">
              <i className="inline-block h-3 border-r-2 border-dashed border-hi" />
              Deadline
            </span>
          </div>
          <Tag tone={plan.status === "approved" ? "ok" : "bl"}>
            {plan.status === "approved" ? "Approved plan" : "Proposed plan"}
          </Tag>
        </div>

        <div className="relative overflow-x-auto border-t border-divider select-none" data-gantt>
          {/* background columns */}
          <div
            className="pointer-events-none absolute inset-0 grid"
            style={{ ...grid, minWidth: minW }}
          >
            <span />
            {days.map((d) => (
              <span
                key={d}
                className={cn(
                  "col-span-2 border-l border-divider-2",
                  dayParts(d).sun && "bg-surface",
                  hot.has(d) && "bg-hi/[0.045]",
                  d === sch.today && "shadow-[inset_2px_0_0_var(--color-primary)]",
                )}
              />
            ))}
          </div>
          <div
            className="relative grid min-h-[52px] items-center bg-surface"
            style={{ ...grid, minWidth: minW }}
          >
            <div className="sticky left-0 z-[3] flex h-full items-center border-r border-line bg-surface px-5 text-xs font-semibold tracking-[0.04em] text-muted uppercase">
              Order
            </div>
            {days.map((d) => {
              const p = dayParts(d);
              return (
                <div
                  key={d}
                  className={cn(
                    "col-span-2 flex flex-col items-center gap-px text-[13px] text-ink-2",
                    p.sun && "text-subtle",
                  )}
                >
                  <small className="text-[11px] text-subtle">{p.dow}</small>
                  <b
                    className={cn(
                      d === sch.today && "rounded-full bg-primary px-[7px] py-px text-white",
                    )}
                  >
                    {p.day}
                  </b>
                </div>
              );
            })}
          </div>

          {running.length > 0 && <Section minW={minW}>In production · locked</Section>}
          {running.map((r) => {
            const info = runInfo[r.id];
            return (
              <Row key={r.id} grid={grid} minW={minW}>
                <div className="sticky left-0 z-[3] col-start-1 row-start-1 flex h-full items-center gap-2.5 border-r border-line bg-white pr-3.5 pl-5">
                  <span className="w-3.5 text-xs opacity-60" title="In production, can't be moved">
                    🔒
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <b className="font-mono text-[13px] font-semibold text-muted">{info?.number}</b>
                    <small className="truncate text-xs text-muted">{info?.customer}</small>
                  </span>
                  <Tag tone="lo" size="sm">
                    {info?.progress ? "Ongoing" : "Planned"}
                  </Tag>
                </div>
                <Bars row={r} days={days}>
                  {(s, style, i) => (
                    <Tooltip
                      key={i}
                      content={
                        <div className="flex w-[240px] flex-col">
                          <b className="mb-1 font-mono">{info?.number}</b>
                          <TipRow label="Customer" value={info?.customer} />
                          <TipRow label="Product" value={info?.product} />
                          <TipRow
                            label="Machine"
                            value={`${s.name} · ${range(s.start, s.finish)}`}
                          />
                          <TipRow
                            label="Status"
                            value={
                              info?.progress
                                ? `In production · ${info.progress}% done`
                                : "Planned earlier"
                            }
                          />
                        </div>
                      }
                    >
                      <div
                        tabIndex={0}
                        className="z-[1] row-start-1 mx-px flex h-[30px] cursor-not-allowed items-center overflow-hidden rounded-[9px] border border-line-input bg-surface-2 px-2 font-mono text-[11px] whitespace-nowrap text-subtle"
                        style={style}
                      >
                        <span className="truncate">{s.name}</span>
                      </div>
                    </Tooltip>
                  )}
                </Bars>
              </Row>
            );
          })}

          <Section minW={minW}>This plan{edit ? " · drag ⋮⋮ to reorder" : ""}</Section>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={ids} strategy={verticalListSortingStrategy}>
              {planned.map((r) => (
                <PlanRow
                  key={r.id}
                  row={r}
                  grid={grid}
                  minW={minW}
                  days={days}
                  plan={plan}
                  editable={edit && !busy}
                  machineOrder={machineOrder}
                  onResize={onResize}
                  onUnpin={() =>
                    void change(
                      { pin: { [r.id]: null } },
                      num(r.id),
                      { pin: { [r.id]: seqRow[r.id]?.pinned ?? null } },
                      `Releasing ${num(r.id)}'s finish date`,
                    )
                  }
                />
              ))}
            </SortableContext>
          </DndContext>

          <Section minW={minW}>Machine load</Section>
          {sch.load.map((l) => (
            <Row key={l.machine} grid={grid} minW={minW} small>
              <div className="sticky left-0 z-[3] col-start-1 row-start-1 flex h-full items-center gap-2.5 border-r border-line bg-white pr-3.5 pl-5 text-sm">
                <i
                  className={cn(
                    "inline-block size-3 rounded-[3px] border bg-current!",
                    machineTone(l.machine, machineOrder),
                  )}
                />
                <span className="flex-1">{l.name}</span>
                {l.over ? (
                  <Tag tone="hi" size="sm">
                    Over
                  </Tag>
                ) : days.some((d) => queued.has(`${l.name}|${d}`)) ? (
                  <Tag tone="md" size="sm">
                    Full
                  </Tag>
                ) : null}
              </div>
              {days.map((d, i) => {
                const v = l.days[d];
                const empty = v === null || v === undefined || v === 0;
                const q = queued.has(`${l.name}|${d}`);
                return (
                  <div
                    key={d}
                    title={q ? `${l.name} fully booked: a late order waits for it` : undefined}
                    className={cn(
                      "z-[1] col-span-2 row-start-1 mx-0.5 grid h-[26px] place-items-center rounded-[5px] text-[11px] font-semibold",
                      empty
                        ? "font-normal text-faint"
                        : v > 100
                          ? "bg-hi text-white"
                          : v >= 90
                            ? "bg-load text-load-ink"
                            : "bg-bl-bg text-bl",
                      q && "ring-2 ring-hi ring-inset",
                    )}
                    style={{ gridColumn: `${2 + i * 2} / span 2` }}
                  >
                    {empty ? "–" : `${v}%`}
                  </div>
                );
              })}
            </Row>
          ))}
        </div>
      </section>

      <div className="flex flex-wrap justify-between gap-3">
        <Button variant="pill" onClick={() => go("2")}>
          ← Proposed sequence
        </Button>
        <Button variant="dark" onClick={() => go("4")}>
          Next: Financial analysis →
        </Button>
      </div>
      {reorder.modal}
    </section>
  );
}

function Section({ children, minW }: { children: ReactNode; minW: number }) {
  return (
    <div
      className="relative z-[2] border-t border-line bg-white px-5 pt-3.5 pb-2 text-xs font-semibold tracking-[0.06em] text-muted uppercase"
      style={{ minWidth: minW }}
    >
      {children}
    </div>
  );
}

function Row({
  children,
  grid,
  minW,
  small,
}: {
  children: ReactNode;
  grid: CSSProperties;
  minW: number;
  small?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative grid items-center border-t border-divider",
        small ? "min-h-10" : "min-h-14",
      )}
      style={{ ...grid, minWidth: minW }}
    >
      {children}
    </div>
  );
}

type Step = GanttRow["steps"][number];

/** Grid placement of each route step inside the visible days (half-days where steps hand over). */
function placements(row: GanttRow, days: string[]) {
  const first = days[0]!;
  const last = days[days.length - 1]!;
  return row.steps.flatMap((s, i) => {
    if (s.finish < first || s.start > last) return [];
    const prev = row.steps[i - 1];
    const next = row.steps[i + 1];
    const startHalf = !!prev && prev.finish === s.start && s.start >= first;
    const endHalf = !!next && next.start === s.finish && s.finish <= last;
    const a = s.start < first ? 0 : days.indexOf(s.start);
    const b = s.finish > last ? days.length - 1 : days.indexOf(s.finish);
    const colA = 2 + a * 2 + (startHalf ? 1 : 0);
    const colB = 2 + b * 2 + (endHalf ? 1 : 2);
    return [
      {
        s,
        i,
        style: { gridColumn: `${colA} / ${colB}` } as CSSProperties,
        clipped: s.start < first || s.finish > last,
      },
    ];
  });
}

function Bars({
  row,
  days,
  children,
}: {
  row: GanttRow;
  days: string[];
  children: (s: Step, style: CSSProperties, i: number) => ReactNode;
}) {
  return <>{placements(row, days).map((p) => children(p.s, p.style, p.i))}</>;
}

/** Share of the first day(s) of a step taken by its setup, in days. */
function setupDays(s: Step): number {
  let left = s.setup;
  let n = 0;
  for (const h of Object.values(s.hours)) {
    if (left <= 0 || h <= 0) break;
    n += Math.min(1, left / h);
    left -= h;
  }
  return n;
}

function PlanRow({
  row,
  grid,
  minW,
  days,
  plan,
  editable,
  machineOrder,
  onResize,
  onUnpin,
}: {
  row: GanttRow;
  grid: CSSProperties;
  minW: number;
  days: string[];
  plan: Plan;
  editable: boolean;
  machineOrder: string[];
  onResize: (id: string, finish: string) => void;
  onUnpin: () => void;
}) {
  const o = plan.result.selection.orders[row.id]!;
  const s = plan.result.sequence.rows.find((x) => x.id === row.id);
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: row.id, disabled: !editable || !!s?.locked });
  const [drag, setDrag] = useState(0); // whole days while dragging the bar's right edge
  const startX = useRef(0);
  const late = (s?.late_days ?? 0) > 0;
  const status = late
    ? { tone: "hi" as const, text: `Late ${plural(s!.late_days, "day")}` }
    : row.short
      ? { tone: "md" as const, text: "Material short" }
      : { tone: "ok" as const, text: "On time" };
  const dayCol = (iso: string) => 2 + days.indexOf(iso) * 2;
  const inView = (iso: string) => days.includes(iso);

  const edgeDown = (e: React.PointerEvent) => {
    if (!editable) return;
    e.stopPropagation();
    e.preventDefault();
    startX.current = e.clientX;
    const box = (
      e.currentTarget.closest("[data-gantt-row]") as HTMLElement
    ).getBoundingClientRect();
    const cellW = (box.width - LABEL_W) / days.length;
    const move = (ev: PointerEvent) => setDrag(Math.round((ev.clientX - startX.current) / cellW));
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const delta = Math.round((ev.clientX - startX.current) / cellW);
      setDrag(0);
      if (delta) onResize(row.id, addDays(row.finish, delta));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const tip = (st: Step) => (
    <div className="flex w-[260px] flex-col">
      <div className="mb-2 flex items-center justify-between">
        <b className="font-mono text-sm">{o.number}</b>
        <Tag tone={status.tone} size="sm">
          {status.text}
        </Tag>
      </div>
      <TipRow label="Customer" value={o.customer} />
      <TipRow label="Product" value={o.product} />
      <TipRow label="Units" value={`${count(o.qty)} ${o.unit}`} />
      <TipRow label="Value" value={rupeesCompact(o.value)} />
      <TipRow label="Deadline" value={shortDate(o.deadline)} />
      <TipRow
        label="Buffer"
        value={s ? (s.buffer < 0 ? `−${plural(-s.buffer, "day")}` : plural(s.buffer, "day")) : "–"}
      />
      <TipRow label="Route" value={row.steps.map((x) => x.name).join(" → ")} />
      <TipRow
        label="This step"
        value={`${st.name} · ${range(st.start, st.finish)}${st.setup ? ` · ${st.setup} h setup` : ""}`}
      />
    </div>
  );

  const places = placements(row, days);
  const lastIdx = row.steps.length - 1;
  return (
    <div
      ref={setNodeRef}
      data-gantt-row
      data-testid={`gantt-${o.number}`}
      className={cn(
        "relative grid min-h-14 items-center border-t border-divider",
        isDragging && "z-10 bg-white opacity-70 shadow-tip",
      )}
      style={{ ...grid, minWidth: minW, transform: CSS.Transform.toString(transform), transition }}
    >
      <div className="sticky left-0 z-[3] col-start-1 row-start-1 flex h-full items-center gap-2.5 border-r border-line bg-white pr-3.5 pl-5">
        <button
          type="button"
          ref={setActivatorNodeRef}
          {...attributes}
          {...listeners}
          aria-label={`Drag to reorder ${o.number}`}
          className={cn(
            "border-0 bg-transparent p-0 text-sm tracking-[-2px] text-faint select-none",
            editable && !s?.locked
              ? "cursor-grab hover:text-ink-3"
              : "cursor-not-allowed opacity-40",
          )}
        >
          ⋮⋮
        </button>
        <span className="grid size-[22px] flex-none place-items-center rounded-full bg-surface-2 text-xs font-semibold text-ink-2">
          {s?.rank}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <b className="font-mono text-[13px] font-semibold">{o.number}</b>
          <small className="truncate text-xs text-muted">{o.customer}</small>
        </span>
        {s?.pinned && (
          <button
            type="button"
            onClick={onUnpin}
            disabled={!editable}
            aria-label={`Release the finish date of ${o.number}`}
            title={`Finish date set to ${shortDate(s.pinned)}. Click to release.`}
            className="cursor-pointer border-0 bg-transparent p-0 text-xs"
          >
            📌
          </button>
        )}
        <Tag tone={status.tone} size="sm">
          {status.text}
        </Tag>
      </div>

      {/* days the order queued for a full machine (why it is late) */}
      {row.wait.map((w) => {
        const span = daysBetween(w.from, w.to).filter(inView);
        if (!span.length) return null;
        return (
          <div
            key={`${w.machine}${w.from}`}
            title={`Waiting for ${w.machine}: fully booked ${range(w.from, w.to)}`}
            className={cn(
              "z-0 row-start-1 h-[30px] rounded-[9px] border border-dashed border-hi-line",
              HATCH,
            )}
            style={{ gridColumn: `${dayCol(span[0]!)} / ${dayCol(span[span.length - 1]!) + 2}` }}
          />
        );
      })}

      {places.map(({ s: st, i, style, clipped }) => {
        const last = i === lastIdx;
        const grow = last && drag ? drag * 2 : 0;
        const col = String(style.gridColumn).split(" / ").map(Number) as [number, number];
        const end = Math.max(col[0] + 1, Math.min(2 + days.length * 2, col[1] + grow));
        const sd = setupDays(st);
        const barDays = (col[1] - col[0]) / 2;
        return (
          <Tooltip key={i} content={tip(st)}>
            <div
              tabIndex={0}
              className={cn(
                "group relative z-[1] row-start-1 mx-px flex h-[30px] items-center overflow-hidden rounded-[9px] border font-mono text-[11px] whitespace-nowrap",
                late && last
                  ? "border-hi-line bg-hi-bg text-hi"
                  : machineTone(st.machine, machineOrder),
                clipped && "rounded-none",
                drag && last && "ring-2 ring-primary",
              )}
              style={{ gridColumn: `${col[0]} / ${end}` }}
            >
              {sd > 0 && !clipped && (
                <span
                  className={cn(
                    "flex h-full flex-none items-center border-r border-md-line px-1.5 text-md",
                    SETUP,
                  )}
                  style={{ width: `${Math.min(100, (100 * sd) / Math.max(barDays, 0.5))}%` }}
                >
                  {sd / Math.max(barDays, 0.5) > 0.3 ? "Setup" : ""}
                </span>
              )}
              <span className="truncate px-2">{st.name}</span>
              {last && editable && !clipped && (
                <span
                  role="separator"
                  aria-label={`Drag to change the finish date of ${o.number}`}
                  onPointerDown={edgeDown}
                  className="absolute top-[6px] right-0.5 bottom-[6px] w-1.5 cursor-ew-resize rounded-sm bg-current opacity-25 group-hover:opacity-60"
                />
              )}
            </div>
          </Tooltip>
        );
      })}

      {row.over_days.filter(inView).map((d) => (
        <div
          key={d}
          title="Machine over capacity"
          className={cn(
            "z-[2] col-span-2 row-start-1 h-[38px] rounded-lg border-2 border-hi",
            HATCH,
          )}
          style={{ gridColumn: `${dayCol(d)} / span 2` }}
        />
      ))}
      {row.short && inView(row.start) && (
        <div
          title="Material short"
          className="z-[3] row-start-1 mt-[3px] -ml-2 grid size-[18px] place-items-center self-start justify-self-start rounded-full bg-md-accent text-xs font-bold text-white"
          style={{ gridColumn: dayCol(row.start) }}
        >
          !
        </div>
      )}
      {row.deadline && inView(row.deadline) && (
        <div
          title={`Deadline ${shortDate(row.deadline)}`}
          className="relative z-[2] row-start-1 h-11 w-0 justify-self-end border-r-2 border-dashed border-hi before:absolute before:-top-1 before:-right-[5px] before:border-x-4 before:border-t-[6px] before:border-x-transparent before:border-t-hi before:content-['']"
          style={{ gridColumn: `${dayCol(row.deadline) + 1}` }}
        />
      )}
    </div>
  );
}
