import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { downloadCsv, toCsv } from "@/lib/csv";
import { ColumnPicker } from "./ColumnPicker";
import { useColumnPrefs, type ColumnInfo } from "./useColumnPrefs";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    label: string;
    align?: "left" | "right";
    mono?: boolean;
    alwaysVisible?: boolean;
    defaultHidden?: boolean;
    /** Value written to CSV. Defaults to the accessor value. */
    csv?: (row: TData) => string | number | null | undefined;
  }
}

export interface ServerPagination {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}

export interface DataTableProps<T> {
  /** Stable id: column choices are saved per user under this key. */
  tableId: string;
  title: ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- TanStack column value types vary per column
  columns: ColumnDef<T, any>[];
  data: T[];
  getRowId: (row: T) => string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  empty?: { title: string; description?: string };
  actions?: ReactNode;
  onRowClick?: (row: T) => void;
  /** Server-side sorting. Omit for client-side sorting. */
  sorting?: { state: SortingState; onChange: (s: SortingState) => void };
  pagination?: ServerPagination;
  csv?: { filename: string; fetchAll?: () => Promise<T[]> };
  /** Rows above this count are virtualised (only visible rows are in the DOM). */
  virtualizeAbove?: number;
  maxHeight?: number;
}

const ROW_HEIGHT = 49;

export function DataTable<T>({
  tableId,
  title,
  columns,
  data,
  getRowId,
  loading,
  error,
  onRetry,
  empty,
  actions,
  onRowClick,
  sorting,
  pagination,
  csv,
  virtualizeAbove = 150,
  maxHeight = 640,
}: DataTableProps<T>) {
  const columnInfo: ColumnInfo[] = useMemo(
    () =>
      columns.map((c) => ({
        id: c.id!,
        label: c.meta?.label ?? c.id!,
        alwaysVisible: c.meta?.alwaysVisible,
        defaultHidden: c.meta?.defaultHidden,
      })),
    [columns],
  );
  const { prefs, update, reset } = useColumnPrefs(tableId, columnInfo);
  const [localSort, setLocalSort] = useState<SortingState>([]);
  const sortState = sorting?.state ?? localSort;

  const table = useReactTable({
    data,
    columns,
    getRowId,
    state: {
      sorting: sortState,
      columnOrder: prefs.order,
      columnVisibility: Object.fromEntries(prefs.hidden.map((id) => [id, false])),
    },
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sortState) : updater;
      if (sorting) sorting.onChange(next);
      else setLocalSort(next);
    },
    manualSorting: !!sorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: sorting ? undefined : getSortedRowModel(),
  });

  const rows = table.getRowModel().rows;
  const visibleCols = table.getVisibleLeafColumns();
  const virtual = rows.length > virtualizeAbove;
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    enabled: virtual,
  });

  const exportCsv = async () => {
    const all = csv?.fetchAll ? await csv.fetchAll() : rows.map((r) => r.original);
    const headers = visibleCols.map((c) => c.columnDef.meta?.label ?? c.id);
    const body = all.map((row) =>
      visibleCols.map((c) => {
        const meta = c.columnDef.meta;
        if (meta?.csv) return meta.csv(row);
        const v = c.accessorFn ? c.accessorFn(row, 0) : undefined;
        return v === null || v === undefined ? "" : (v as string | number);
      }),
    );
    downloadCsv(csv!.filename, toCsv(headers, body));
  };

  const renderRow = (row: Row<T>) => (
    <tr
      key={row.id}
      data-index={row.index}
      onClick={onRowClick ? () => onRowClick(row.original) : undefined}
      onKeyDown={
        onRowClick
          ? (e) => {
              if (e.key === "Enter") onRowClick(row.original);
            }
          : undefined
      }
      tabIndex={onRowClick ? 0 : undefined}
      className={cn(onRowClick && "cursor-pointer hover:bg-surface focus-visible:bg-surface")}
    >
      {row.getVisibleCells().map((cell) => {
        const meta = cell.column.columnDef.meta;
        return (
          <td
            key={cell.id}
            className={cn(
              "border-t border-divider px-4 py-3.5 text-sm whitespace-nowrap text-ink",
              meta?.align === "right" && "text-right tabular-nums",
              meta?.mono && "font-mono",
            )}
          >
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </td>
        );
      })}
    </tr>
  );

  const vItems = virtual ? virtualizer.getVirtualItems() : [];
  const padTop = virtual && vItems.length ? vItems[0]!.start : 0;
  const padBottom =
    virtual && vItems.length ? virtualizer.getTotalSize() - vItems[vItems.length - 1]!.end : 0;

  return (
    <section className="rounded-card border border-line bg-white" aria-busy={loading || undefined}>
      <CardHeader
        title={title}
        actions={
          <>
            {actions}
            {csv && (
              <Button variant="pill" onClick={exportCsv} disabled={loading || rows.length === 0}>
                Export CSV
              </Button>
            )}
            <ColumnPicker columns={columnInfo} prefs={prefs} onChange={update} onReset={reset} />
          </>
        }
      />
      {error ? (
        <ErrorState message={error} onRetry={onRetry} />
      ) : (
        <div
          ref={scrollRef}
          className="overflow-auto"
          style={virtual ? { maxHeight } : undefined}
          data-testid={`table-${tableId}`}
        >
          <table className="w-full border-collapse font-sans">
            <thead className="sticky top-0 z-[1] bg-surface">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => {
                    const meta = h.column.columnDef.meta;
                    const sortable = h.column.getCanSort();
                    const dir = h.column.getIsSorted();
                    return (
                      <th
                        key={h.id}
                        scope="col"
                        aria-sort={
                          dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined
                        }
                        className={cn(
                          "px-4 py-3 text-left text-xs font-semibold tracking-[.04em] whitespace-nowrap text-muted uppercase",
                          meta?.align === "right" && "text-right",
                        )}
                      >
                        {sortable ? (
                          <button
                            type="button"
                            onClick={h.column.getToggleSortingHandler()}
                            className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-xs font-semibold tracking-[.04em] text-muted uppercase hover:text-ink"
                          >
                            {flexRender(h.column.columnDef.header, h.getContext())}
                            <span aria-hidden className={cn("text-[10px]", !dir && "opacity-0")}>
                              {dir === "desc" ? "▼" : "▲"}
                            </span>
                          </button>
                        ) : (
                          flexRender(h.column.columnDef.header, h.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    {visibleCols.map((c) => (
                      <td key={c.id} className="border-t border-divider px-4 py-3.5">
                        <Skeleton className="h-4 w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={visibleCols.length} className="border-t border-divider p-6">
                    <EmptyState
                      title={empty?.title ?? "Nothing here yet"}
                      description={empty?.description}
                      className="border-0 bg-transparent py-8"
                    />
                  </td>
                </tr>
              ) : virtual ? (
                <>
                  {padTop > 0 && <tr style={{ height: padTop }} aria-hidden />}
                  {vItems.map((vi) => renderRow(rows[vi.index]!))}
                  {padBottom > 0 && <tr style={{ height: padBottom }} aria-hidden />}
                </>
              ) : (
                rows.map(renderRow)
              )}
            </tbody>
          </table>
        </div>
      )}
      {pagination && pagination.total > 0 && !error && <Pager {...pagination} />}
    </section>
  );
}

function Pager({ total, limit, offset, onChange }: ServerPagination) {
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="flex items-center justify-between gap-3 border-t border-divider px-5 py-3 text-[13px] text-muted">
      <span>
        {from.toLocaleString("en-IN")}–{to.toLocaleString("en-IN")} of{" "}
        {total.toLocaleString("en-IN")}
      </span>
      <div className="flex gap-2">
        <Button
          variant="pill"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          ← Previous
        </Button>
        <Button variant="pill" disabled={to >= total} onClick={() => onChange(offset + limit)}>
          Next →
        </Button>
      </div>
    </div>
  );
}
