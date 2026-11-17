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
  /** Shown next to the title, e.g. "Showing 1–8 of 248". Defaults to that text when paginated. */
  subtitle?: ReactNode;
  /** Row checkboxes (ids of the selected rows). */
  selection?: { selected: string[]; onChange: (ids: string[]) => void; label?: (row: T) => string };
  /** Extra row under the header (bulk actions, filter summary). */
  toolbar?: ReactNode;
  /** Total number of fields the API offers (shown in the footer). */
  availableFields?: number;
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
  subtitle,
  selection,
  toolbar,
  availableFields,
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
      className={cn(
        onRowClick && "cursor-pointer hover:bg-surface focus-visible:bg-surface",
        selection?.selected.includes(row.id) && "bg-surface-blue",
      )}
    >
      {selection && (
        <td
          className="w-10 border-t border-divider py-3.5 pr-0 pl-4"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            className="size-4"
            aria-label={`Select ${selection.label ? selection.label(row.original) : row.id}`}
            checked={selection.selected.includes(row.id)}
            onChange={(e) =>
              selection.onChange(
                e.target.checked
                  ? [...selection.selected, row.id]
                  : selection.selected.filter((x) => x !== row.id),
              )
            }
          />
        </td>
      )}
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

  const pageIds = rows.map((r) => r.id);
  const allOnPage =
    selection && pageIds.length > 0 && pageIds.every((id) => selection.selected.includes(id));
  const defaultSubtitle =
    pagination && pagination.total > 0
      ? `Showing ${(pagination.offset + 1).toLocaleString("en-IN")}–${Math.min(pagination.offset + pagination.limit, pagination.total).toLocaleString("en-IN")} of ${pagination.total.toLocaleString("en-IN")}`
      : undefined;
  const vItems = virtual ? virtualizer.getVirtualItems() : [];
  const padTop = virtual && vItems.length ? vItems[0]!.start : 0;
  const padBottom =
    virtual && vItems.length ? virtualizer.getTotalSize() - vItems[vItems.length - 1]!.end : 0;

  return (
    <section className="rounded-card border border-line bg-card" aria-busy={loading || undefined}>
      <CardHeader
        title={
          <span className="flex flex-wrap items-baseline gap-3">
            {title}
            {(subtitle ?? defaultSubtitle) && (
              <span className="text-[13px] font-normal text-muted">
                {subtitle ?? defaultSubtitle}
              </span>
            )}
          </span>
        }
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
      {toolbar}
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
                  {selection && (
                    <th scope="col" className="w-10 py-3 pr-0 pl-4">
                      <input
                        type="checkbox"
                        className="size-4"
                        aria-label="Select all rows on this page"
                        checked={!!allOnPage}
                        onChange={(e) =>
                          selection.onChange(
                            e.target.checked
                              ? [...new Set([...selection.selected, ...pageIds])]
                              : selection.selected.filter((x) => !pageIds.includes(x)),
                          )
                        }
                      />
                    </th>
                  )}
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
                            <span
                              aria-hidden
                              className={cn("ml-0.5 text-[11px]", dir ? "text-ink" : "text-subtle")}
                            >
                              {dir === "desc" ? "↓" : dir === "asc" ? "↑" : "↕"}
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
                  <td
                    colSpan={visibleCols.length + (selection ? 1 : 0)}
                    className="border-t border-divider p-6"
                  >
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
      {!error && (pagination || availableFields) && (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-divider px-5 py-3">
          <span className="text-[13px] text-muted">
            {visibleCols.length} columns visible · {availableFields ?? columnInfo.length} available
            fields
          </span>
          {pagination && pagination.total > pagination.limit && <Pager {...pagination} />}
        </div>
      )}
    </section>
  );
}

function pageList(current: number, last: number): (number | "…")[] {
  const set = new Set(
    [1, last, current - 1, current, current + 1].filter((p) => p >= 1 && p <= last),
  );
  const sorted = [...set].sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1]! > 1) out.push("…");
    out.push(p);
  });
  return out;
}

function Pager({ total, limit, offset, onChange }: ServerPagination) {
  const last = Math.max(1, Math.ceil(total / limit));
  const current = Math.floor(offset / limit) + 1;
  const go = (p: number) => onChange((p - 1) * limit);
  const btn =
    "min-w-8 h-8 cursor-pointer rounded-full border-0 bg-transparent px-2.5 text-[13px] font-medium text-ink-2 hover:bg-surface-2 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";
  return (
    <nav aria-label="Pagination" className="flex items-center gap-1">
      <button
        type="button"
        className={btn}
        disabled={current === 1}
        onClick={() => go(current - 1)}
      >
        ‹ Previous
      </button>
      {pageList(current, last).map((p, i) =>
        p === "…" ? (
          <span key={`gap-${i}`} className="px-1 text-[13px] text-subtle">
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            aria-current={p === current ? "page" : undefined}
            className={cn(btn, p === current && "bg-bl-bg font-semibold text-bl hover:bg-bl-bg")}
            onClick={() => go(p)}
          >
            {p}
          </button>
        ),
      )}
      <button
        type="button"
        className={btn}
        disabled={current === last}
        onClick={() => go(current + 1)}
      >
        Next ›
      </button>
    </nav>
  );
}
