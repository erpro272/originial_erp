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
import { Button, Caret } from "@/components/ui/Button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";
import type { ColumnInfo, ColumnPrefs } from "./useColumnPrefs";

function Row({
  col,
  visible,
  onToggle,
}: {
  col: ColumnInfo;
  visible: boolean;
  onToggle: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: col.id,
  });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-surface",
        isDragging && "relative z-10 bg-card shadow-lift",
      )}
    >
      <button
        type="button"
        aria-label={`Reorder ${col.label}`}
        className="cursor-grab border-0 bg-transparent px-1 tracking-[-2px] text-faint hover:text-ink-3"
        {...attributes}
        {...listeners}
      >
        ⋮⋮
      </button>
      <label className="flex flex-1 cursor-pointer items-center gap-2 text-ink-2">
        <input
          type="checkbox"
          className="size-4"
          checked={visible}
          disabled={col.alwaysVisible}
          onChange={onToggle}
        />
        {col.label}
      </label>
    </li>
  );
}

/** "Columns (N) ▾": show/hide and drag to reorder. Changes save per user. */
export function ColumnPicker({
  columns,
  prefs,
  onChange,
  onReset,
}: {
  columns: ColumnInfo[];
  prefs: ColumnPrefs;
  onChange: (p: ColumnPrefs) => void;
  onReset: () => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const byId = new Map(columns.map((c) => [c.id, c]));
  const visibleCount = prefs.order.filter((id) => !prefs.hidden.includes(id)).length;

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = prefs.order.indexOf(String(active.id));
    const to = prefs.order.indexOf(String(over.id));
    onChange({ ...prefs, order: arrayMove(prefs.order, from, to) });
  };
  const toggle = (id: string) =>
    onChange({
      ...prefs,
      hidden: prefs.hidden.includes(id)
        ? prefs.hidden.filter((h) => h !== id)
        : [...prefs.hidden, id],
    });

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="pill">
          Columns ({visibleCount}) <Caret />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64">
        <div className="flex items-center justify-between px-2 pb-2">
          <span className="text-xs font-semibold tracking-[.04em] text-muted uppercase">
            Show columns
          </span>
          <button
            type="button"
            onClick={onReset}
            className="cursor-pointer border-0 bg-transparent text-xs font-medium text-link"
          >
            Reset
          </button>
        </div>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={prefs.order} strategy={verticalListSortingStrategy}>
            <ul className="m-0 max-h-80 list-none overflow-y-auto p-0">
              {prefs.order.map((id) => {
                const col = byId.get(id);
                return col ? (
                  <Row
                    key={id}
                    col={col}
                    visible={!prefs.hidden.includes(id)}
                    onToggle={() => toggle(id)}
                  />
                ) : null;
              })}
            </ul>
          </SortableContext>
        </DndContext>
      </PopoverContent>
    </Popover>
  );
}
