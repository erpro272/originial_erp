import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { api, unwrap } from "@/api/client";

export interface ColumnPrefs {
  order: string[];
  hidden: string[];
}
export interface ColumnInfo {
  id: string;
  label: string;
  alwaysVisible?: boolean;
  defaultHidden?: boolean;
}

/** Merge saved prefs with the current column list (new columns appear, removed ones drop). */
export function resolvePrefs(columns: ColumnInfo[], saved: Partial<ColumnPrefs> | undefined) {
  const ids = columns.map((c) => c.id);
  const order = [...(saved?.order ?? []).filter((id) => ids.includes(id))];
  for (const id of ids) if (!order.includes(id)) order.push(id);
  const hidden = new Set(saved?.hidden ?? columns.filter((c) => c.defaultHidden).map((c) => c.id));
  for (const c of columns) if (c.alwaysVisible) hidden.delete(c.id);
  return { order, hidden: [...hidden].filter((id) => ids.includes(id)) };
}

/** Column order/visibility, saved per user via /api/me/preferences/table.<id>.columns. */
export function useColumnPrefs(tableId: string, columns: ColumnInfo[]) {
  const key = `table.${tableId}.columns`;
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["prefs", key],
    queryFn: async () =>
      unwrap(await api.GET("/api/me/preferences/{key}", { params: { path: { key } } }))
        .value as Partial<ColumnPrefs>,
    staleTime: Infinity,
  });
  const save = useMutation({
    mutationFn: async (value: ColumnPrefs) =>
      unwrap(
        await api.PUT("/api/me/preferences/{key}", {
          params: { path: { key } },
          body: { value: value as unknown as Record<string, unknown> },
        }),
      ),
  });
  // Local state makes each change visible in the same render (the query cache notifies
  // observers on a later tick, which would make controlled checkboxes flicker).
  const [local, setLocal] = useState<ColumnPrefs | undefined>();
  const effective = local ?? query.data;
  const prefs = useMemo(() => resolvePrefs(columns, effective), [columns, effective]);
  // Update the cache synchronously (no flicker on controlled checkboxes), then save.
  const { mutate } = save;
  const update = useCallback(
    (next: ColumnPrefs) => {
      setLocal(next);
      qc.setQueryData(["prefs", key], next);
      mutate(next);
    },
    [qc, key, mutate],
  );
  const reset = useCallback(() => update(resolvePrefs(columns, undefined)), [columns, update]);
  return { prefs, update, reset, loaded: query.isSuccess || query.isError };
}
