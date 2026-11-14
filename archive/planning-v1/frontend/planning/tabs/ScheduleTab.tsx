import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useRef, useState, type CSSProperties } from "react";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { TipRow, Tooltip } from "@/components/ui/Menu";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { count, rupeesCompact, shortDate } from "@/lib/format";
import { machineTone, usePatchPlan, type GanttRow, type PlanPatch } from "../api";
import { dayParts, plural, range } from "../format";
import type { TabProps } from "../PlanningPage";
import { useReorder } from "../reorder";

const LABEL_W = 290;
const DAY_W = 46;

export function ScheduleTab({ plan, go }: TabProps) {
  const { can } = useAuth();
  const edit = can("planning.write");
  const sch = plan.result.schedule;
  const seq = plan.result.sequence;
  const o = plan.result.selection.orders;
  const reorder = useReorder(plan);
  const patch = usePatchPlan(plan.id);
  const [undo, setUndo] = useState<{ body: PlanPatch; label: string }[]>([]);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const days = sch.days;
  const col = (iso: string) => days.indexOf(iso) + 2;
  const grid: CSSProperties = {
    gridTemplateColumns: `${LABEL_W}px repeat(${days.length}, minmax(${DAY_W}px, 1fr))`,
  };
  const minW = LABEL_W + days.length * DAY_W;
  const machineOrder = sch.load.map((l) => l.machine);
  const hot = new Set(sch.rows.flatMap((r) => r.over_days));
  const running = sch.rows.filter((r) => r.running);
  const planned = sch.rows.filter((r) => !r.running);
  const ids = planned.map((r) => r.id);
  const seqRow = Object.fromEntries(seq.rows.map((r) => [r.id, r]));
  const runInfo = Object.fromEntries(plan.result.selection.running.map((r) => [r.id, r]));

  const change = async (body: PlanPatch, label: string, inverse: PlanPatch) => {
    await reorder.request(body, label);
    setUndo((u) => [...u.slice(-19), { body: inverse, label }]);
  };
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const next = arrayMove(ids, ids.indexOf(String(e.active.id)), ids.indexOf(String(e.over.id)));
    void change({ sequence: next }, o[String(e.active.id)]?.number ?? "", { sequence: ids });
  };
  const onResize = (id: string, newFinish: string) => {
    const prev = seqRow[id]?.pinned ?? null;
    void change({ pin: { [id]: newFinish } }, o[id]?.number ?? "", { pin: { [id]: prev } });
  };

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em]">Production schedule</h2>
          <p className="m-0 text-sm text-muted">
            Which machine runs which order, day by day. Drag an order by ⋮⋮ to reorder it, or drag a
            bar's right edge to change its finish date.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="pill"
            size="pill"
            disabled={!undo.length || patch.isPending}
            onClick={async () => {
              const last = undo[undo.length - 1]!;
              setUndo((u) => u.slice(0, -1));
              await patch.mutateAsync(last.body);
            }}
          >
            ↶ Undo
          </Button>
          <span className="rounded-full border border-line-input px-3.5 py-2 text-[13px] font-medium text-ink-2">
            {range(days[0], days[days.length - 1])} {days[0]?.slice(0, 4)}
          </span>
          <span className="text-[13px] text-muted">Changes save automatically</span>
        </div>
      </div>

      {sch.bottlenecks.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {sch.bottlenecks.map((b) => (
            <div
              key={`${b.kind}${b.resource}${b.from}`}
              className="flex items-center gap-2.5 rounded-full border border-hi-line bg-hi-wash px-4 py-2 text-sm"
            >
              <span className="size-2 rounded-full bg-hi" />
              <b>{b.title}</b>
              <span className="text-muted">
                {b.text}
                {b.kind === "machine" && b.orders.length
                  ? ` · ${b.orders.map((i) => o[i]?.number).join(" & ")}`
                  : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      <section className="overflow-hidden rounded-card border border-line">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex flex-wrap gap-4 text-[13px] text-ink-3">
            {sch.load.map((l) => (
              <span key={l.machine} className="flex items-center gap-1.5">
                <i
                  className={cn(
                    "inline-block size-3 rounded-[3px] border",
                    machineTone(l.machine, machineOrder),
                  )}
                />
                {l.name}
              </span>
            ))}
            <span className="flex items-center gap-1.5">
              <i className="inline-block size-3 rounded-[3px] border border-line-input bg-surface-2" />
              In production
            </span>
            <span className="flex items-center gap-1.5">
              <i className="inline-block size-3 rounded-[3px] border-2 border-hi bg-[repeating-linear-gradient(135deg,color-mix(in_srgb,var(--color-hi)_25%,transparent)_0_2px,transparent_2px_4px)]" />
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

        <div className="relative overflow-x-auto border-t border-divider select-none">
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
                  "border-l border-divider-2",
                  dayParts(d).sun && "bg-surface",
                  hot.has(d) && "bg-hi/[0.045]",
                  d === sch.today && "shadow-[inset_2px_0_0_var(--color-primary)]",
                )}
              />
            ))}
          </div>
          <div
            className="relative grid min-h-[52px] items-center border-0 bg-surface"
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
                    "flex flex-col items-center gap-px text-[13px] text-ink-2",
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
          {running.map((r) => (
            <div
              key={r.id}
              className="relative grid min-h-14 items-center border-t border-divider"
              style={{ ...grid, minWidth: minW }}
            >
              <div className="sticky left-0 z-[3] col-start-1 row-start-1 flex h-full items-center gap-2.5 border-r border-line bg-white pr-3.5 pl-5">
                <span className="w-3.5 text-xs opacity-60" title="Can't be moved">
                  🔒
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <b className="font-mono text-[13px] font-semibold text-muted">
                    {runInfo[r.id]?.number}
                  </b>
                  <small className="truncate text-xs text-muted">{runInfo[r.id]?.customer}</small>
                </span>
                <Tag tone="lo" size="sm">
                  {runInfo[r.id]?.progress ? `${runInfo[r.id]?.progress}% done` : "Booked"}
                </Tag>
              </div>
              {r.steps.map((s, i) => (
                <Tooltip
                  key={i}
                  content={
                    <div className="flex w-[240px] flex-col">
                      <b className="mb-1 font-mono">{runInfo[r.id]?.number}</b>
                      <TipRow label="Customer" value={runInfo[r.id]?.customer} />
                      <TipRow label="Product" value={runInfo[r.id]?.product} />
                      <TipRow label="Machine" value={s.name} />
                      <TipRow label="Dates" value={range(s.start, s.finish)} />
                      <TipRow
                        label="Status"
                        value={
                          runInfo[r.id]?.progress
                            ? `${runInfo[r.id]?.progress}% done`
                            : "Planned earlier"
                        }
                      />
                    </div>
                  }
                >
                  <div
                    tabIndex={0}
                    className="z-[1] row-start-1 mx-px flex h-[30px] cursor-not-allowed items-center overflow-hidden rounded-[9px] border border-line-input bg-surface-2 px-2 font-mono text-[11px] whitespace-nowrap text-subtle"
                    style={{ gridColumn: `${col(s.start)} / ${col(s.finish) + 1}` }}
                  >
                    <span className="truncate">{s.name}</span>
                  </div>
                </Tooltip>
              ))}
            </div>
          ))}

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
                  editable={edit}
                  machineOrder={machineOrder}
                  onResize={onResize}
                  onUnpin={() =>
                    void change({ pin: { [r.id]: null } }, o[r.id]?.number ?? "", {
                      pin: { [r.id]: seqRow[r.id]?.pinned ?? null },
                    })
                  }
                />
              ))}
            </SortableContext>
          </DndContext>

          <Section minW={minW}>Machine load</Section>
          {sch.load.map((l) => (
            <div
              key={l.machine}
              className="relative grid min-h-10 items-center border-t border-divider"
              style={{ ...grid, minWidth: minW }}
            >
              <div className="sticky left-0 z-[3] col-start-1 row-start-1 flex h-full items-center gap-2.5 border-r border-line bg-white pr-3.5 pl-5 text-sm">
                <i
                  className={cn(
                    "inline-block size-3 rounded-[3px] border",
                    machineTone(l.machine, machineOrder),
                  )}
                />
                <span className="flex-1">{l.name}</span>
                {l.over && (
                  <Tag tone="hi" size="sm">
                    Over
                  </Tag>
                )}
              </div>
              {days.map((d) => {
                const v = l.days[d];
                return (
                  <div
                    key={d}
                    className={cn(
                      "z-[1] row-start-1 mx-0.5 grid h-[26px] place-items-center rounded-[5px] text-[11px] font-semibold",
                      v === null || v === undefined || v === 0
                        ? "font-normal text-faint"
                        : v > 100
                          ? "bg-hi text-white"
                          : v > 70
                            ? "bg-load text-load-ink"
                            : "bg-bl-bg text-bl",
                    )}
                    style={{ gridColumn: col(d) }}
                  >
                    {v === null || v === undefined || v === 0 ? "–" : `${v}%`}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </section>

      <div className="flex justify-between">
        <Button variant="pill" onClick={() => go(2)}>
          ← Proposed sequence
        </Button>
        <Button variant="dark" onClick={() => go(4)}>
          Next: Financial analysis →
        </Button>
      </div>
      {reorder.modal}
    </section>
  );
}

function Section({ children, minW }: { children: React.ReactNode; minW: number }) {
  return (
    <div
      className="relative z-[2] border-t border-line bg-white px-5 pt-3.5 pb-2 text-xs font-semibold tracking-[0.06em] text-muted uppercase"
      style={{ minWidth: minW }}
    >
      {children}
    </div>
  );
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
  plan: TabProps["plan"];
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
  } = useSortable({
    id: row.id,
    disabled: !editable || !!s?.locked,
  });
  const col = (iso: string) => days.indexOf(iso) + 2;
  const [drag, setDrag] = useState(0); // day delta while dragging a bar edge
  const startX = useRef(0);
  const late = (s?.late_days ?? 0) > 0;
  const status = late
    ? { tone: "hi" as const, text: `Late ${plural(s!.late_days, "day")}` }
    : row.short
      ? { tone: "md" as const, text: "Material short" }
      : { tone: "ok" as const, text: "On time" };

  const edgeDown = (e: React.PointerEvent) => {
    if (!editable) return;
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    startX.current = e.clientX;
    const cellW =
      ((e.currentTarget.closest("[data-gantt-row]") as HTMLElement).getBoundingClientRect().width -
        290) /
      days.length;
    const move = (ev: PointerEvent) => setDrag(Math.round((ev.clientX - startX.current) / cellW));
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const delta = Math.round((ev.clientX - startX.current) / cellW);
      setDrag(0);
      if (delta) {
        const i = Math.max(0, Math.min(days.length - 1, days.indexOf(row.finish) + delta));
        onResize(row.id, days[i]!);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const tip = (machine: string, a: string, b: string, setup: number) => (
    <div className="flex w-[260px] flex-col">
      <b className="mb-1 font-mono">{o.number}</b>
      <TipRow label="Customer" value={o.customer} />
      <TipRow label="Product" value={o.product} />
      <TipRow label="Units" value={`${count(o.qty)} ${o.unit}`} />
      <TipRow label="Value" value={rupeesCompact(o.value)} />
      <TipRow label="Machine" value={`${machine} · ${range(a, b)}`} />
      {setup > 0 && <TipRow label="Setup" value={`${setup} hrs`} />}
      <TipRow label="Deadline" value={shortDate(o.deadline)} />
      <TipRow
        label="Buffer"
        value={s ? (s.buffer < 0 ? `−${plural(-s.buffer, "day")}` : plural(s.buffer, "day")) : "–"}
      />
      <TipRow label="Status" value={status.text} />
    </div>
  );

  return (
    <div
      ref={setNodeRef}
      data-gantt-row
      className={cn(
        "relative grid min-h-14 items-center border-t border-divider",
        isDragging && "shadow-pop z-10 bg-white opacity-70",
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
            title={`Finish pinned to ${shortDate(s.pinned)}. Click to release.`}
            className="cursor-pointer border-0 bg-transparent p-0 text-xs"
          >
            📌
          </button>
        )}
        <Tag tone={status.tone} size="sm">
          {status.text}
        </Tag>
      </div>
      {row.steps.map((st, i) => {
        const last = i === row.steps.length - 1;
        const end =
          last && drag
            ? Math.max(col(st.start), Math.min(col(days[days.length - 1]!), col(st.finish) + drag))
            : col(st.finish);
        return (
          <Tooltip key={i} content={tip(st.name, st.start, st.finish, st.setup)}>
            <div
              tabIndex={0}
              className={cn(
                "group relative z-[1] row-start-1 mx-px flex h-[30px] items-center overflow-hidden rounded-[4px] border px-2 font-mono text-[11px] whitespace-nowrap",
                i === 0 && "rounded-l-[9px]",
                last && "rounded-r-[9px]",
                late && last
                  ? "border-hi-line bg-hi-bg text-hi"
                  : machineTone(st.machine, machineOrder),
                st.setup > 0 &&
                  "bg-[linear-gradient(90deg,var(--color-md-bg)_0_10px,transparent_10px)]",
              )}
              style={{ gridColumn: `${col(st.start)} / ${end + 1}` }}
            >
              <span className="truncate">{st.name}</span>
              {last && editable && (
                <span
                  role="separator"
                  aria-label={`Drag to change the finish date of ${o.number}`}
                  onPointerDown={edgeDown}
                  className="absolute top-[7px] right-0.5 bottom-[7px] w-1.5 cursor-ew-resize rounded-sm bg-current opacity-0 group-hover:opacity-45"
                />
              )}
            </div>
          </Tooltip>
        );
      })}
      {row.over_days.map((d) => (
        <div
          key={d}
          title="Machine over capacity"
          className="z-[2] row-start-1 -mx-px h-[38px] rounded-lg border-2 border-hi bg-[repeating-linear-gradient(135deg,color-mix(in_srgb,var(--color-hi)_16%,transparent)_0_4px,transparent_4px_9px)]"
          style={{ gridColumn: col(d) }}
        />
      ))}
      {row.short && (
        <div
          title="Material short"
          className="z-[3] row-start-1 mt-[5px] -ml-2 grid size-[18px] place-items-center self-start justify-self-start rounded-full bg-md-accent text-xs font-bold text-white"
          style={{ gridColumn: col(row.start) }}
        >
          !
        </div>
      )}
      {row.deadline && days.includes(row.deadline) && (
        <div
          title={`Deadline ${shortDate(row.deadline)}`}
          className="relative z-[2] row-start-1 h-11 w-0 justify-self-end border-r-2 border-dashed border-hi"
          style={{ gridColumn: col(row.deadline) }}
        />
      )}
    </div>
  );
}
